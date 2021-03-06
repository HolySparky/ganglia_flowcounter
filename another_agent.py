#!/usr/bin/env python
# vim: set fileencoding=utf-8:
import ConfigParser
import logging
import MySQLdb
import os
import sys
import time
import datetime

import subprocess
import threading

import socket
import simplejson as json
from optparse import OptionParser
from sqlalchemy.ext.sqlsoup import SqlSoup


OUT_PORT_NAME = 'int-br-eth2'
OUT_PORT = "0"
EXT_PORT = "eth2"
ports = {}
#ports = {port_name : Port_Info}

#neutron_ports is ports info get from neutron mysql DB

#ip_ports[ip.ip] = {"port_name":ip.port_name, "host_ip":ip.host_ip}

class Flow_Info:
    def __init__(self):
        self.src_host = ""
        self.dst_host = ""
        self.src_ip = ""
        self.dst_ip = ""

    def set_host(self, src, dst):
        self.src_host = src
        self.dst_host = dst

def run_cmd(args):
    return subprocess.Popen(args, stdout=subprocess.PIPE).communicate()[0]

def run_vsctl(args):
    full_args = ["ovs-vsctl"] + args
    return run_cmd(full_args)

def run_dpctl(args):
        full_args = ["ovs-dpctl"] + args
        return run_cmd(full_args)

def get_taps():
    args = ['list-ports', 'br-int']
    result = run_vsctl(args)
#    return [i for i in result.strip().split('\n') if i.startswith('tap')]
    return result

def run_tc(args):
    full_args = ["tc"] + args
    return run_cmd(full_args)

   




def set_db_attribute(table_name, record, column, value):
    args = ["set", table_name, record, "%s=%s" % (column, value)]
    return run_vsctl(args)

def set_interface_ingress_policing_rate(record, value):
    set_db_attribute('Interface', record, 'ingress_policing_rate', int(value))
    set_db_attribute('Interface', record, 'ingress_policing_burst', int(value / 10))

def clear_db_attribute(table_name, record, column):
    args = ["clear", table_name, record, column]
    return run_vsctl(args)
############################################
#Class: Ports and Flows
class PortInfo:
    
    def __init__(self, pid="0", name='tap0', tenant="", network="",device_name=""):
        self.port_id = pid
        self.port_name = name
        self.tenant_id = tenant
        self.network_id = network
        self.device_name = device_name
        self.tx_bytes = []
        self.rx_bytes = []
        self.tx_rate = 0
        self.rx_rate = 0
        self.flows = {}
        self.in_flows = {}
        #flow: {dstIP:[bytes, rate, cap]}
        #in_flow: {srcIP:[bytes, rate]}
# For flow: inpoty:6,dstIP:192.168.1.18 ---> in TC:      class_id = 1:6   flow_id = 1:618

    def UpdateTxRate(self, tx):
        if len(self.tx_bytes) > 2:
            self.tx_bytes.pop(0)
        self.tx_bytes.append(int(tx))
        rate = [-1]
        for i in xrange(len(self.tx_bytes) - 1):
            rate.append(self.tx_bytes[i + 1] - self.tx_bytes[i])
        rate.sort()
        #rate_max = self.tx_bytes[-1] - self.tx_bytes[-2]
        #if self.tx_cap >= 0 and rate_max > self.tx_cap:
        #    rate_max = self.tx_cap
        rate_max = rate[-1] * 8
        self.tx_rate = rate_max
        #if self.port_name =='tapbbb7fbd5-c8':
        #       myfile = open('txrate.txt', 'a')
        #       myfile.write("%s\n" %rate_max)
        #       myfile.close()

#    def UpdateRxRate(self, rx):
#        if len(self.rx_bytes) > 2:
#            self.rx_bytes.pop(0)
#        self.rx_bytes.append(int(rx))
#        rate = [-1]
#        for i in xrange(len(self.rx_bytes) - 1):
#            rate.append(self.rx_bytes[i + 1] - self.rx_bytes[i])
#        rate.sort()
#       rate_max = rate[-1] * 8
#        self.rx_rate = rate_max
    def UpdateRxRate(self):
        self.rx_rate = 0
        for flow in self.in_flows:
            self.rx_rate += int(self.in_flows[flow].tx_rate)

    def UpdateRates(self, tx, rx):
        self.UpdateTxRate(tx)
        self.UpdateRxRate()
        
    def add_flow(self,srcIP, dstIP,tx_byte):
        if dstIP in self.flows:
            self.flows[dstIP].add_txbyte(tx_byte)
        else:
            self.flows[dstIP] = FlowInfo(srcIP,dstIP)
            self.flows[dstIP].add_txbyte(tx_byte)

    def add_in_flow(self, srcIP, dstIP,tx_byte):
        if srcIP in self.in_flows:
            self.in_flows[srcIP].add_txbyte(tx_byte)
        else:
            self.in_flows[srcIP] = FlowInfo(srcIP, dstIP)
            self.in_flows[srcIP].add_txbyte(tx_byte)

	
        

class FlowInfo:
    def __init__(self,srcIP,dstIP):
        self.dst_ip = dstIP
        self.src_ip = ""
        self.tx_bytes = [0,0]
        self.tx_rate = 0
        self.tx_cap = 0


    def add_txbyte(self,tx):
        if len(self.tx_bytes) > 2:
            self.tx_bytes.pop(0)
        self.tx_bytes.append(int(tx))
        rate = [-1]
        for i in xrange(len(self.tx_bytes) - 1):
            rate.append(self.tx_bytes[i + 1] - self.tx_bytes[i])
        rate.sort()
        rate_max = rate[-1] * 8
        self.tx_rate = rate_max
        

    def update(self):
        self.rate = self.tx_byte[1]-self.tx_byte[0]
        if self.rate <= 0:
            self.rate = 0
        self.tx_byte.pop(0)
 

######################################################################
#New ways to get ports and traffic statistics 

def get_ports():
        global ports
        global OUT_PORT
        global OUT_PORT_NAME
        args = ['show', '-s']
        raw_port = run_dpctl(args)
        port_map = {}
        #    return [i for i in result.strip().split('\n') if i.startswith('tap')]
        for i in raw_port.strip().split('port'): #for every port
            port_info = i.split('\t\t')
            port_id = port_info[0].split(':')[0]
            port_id = port_id[1:] 
            port_name = port_info[0].split(':')[1][1:].split(' ')[0]
			#tapa185c58a-64 (internal)
            if port_name.endswith('\n'):
                port_name = port_name[:-1]
            port_traffic = port_info[-1].split(' ')
                #['RX', 'bytes:27716431', '(26.4', 'MiB)', '', 'TX', 'bytes:2301368922', '(2.1', 'GiB)\n\t']
            rx = port_traffic[1].split(':')[-1]
            tx = port_traffic[-3].split(':')[-1]
            if tx=='':
                tx = '0'
            if rx == '':
                rx = '0'
            
            if port_name in ports:
                ports[port_name].UpdateRates(rx, tx)
		#print "already there:"+port_name+":"+ str(ports[port_name].tx_rate)
            else:
                if port_name.startswith("tap"):
                    neutron_port_id = port_name[3:]
                    for neutron_port in neutron_ports:
                        if neutron_port_id == neutron_port.id[0:11]:
                            print "We got a match!!"
                            print neutron_port.device_id
                            ports[port_name] = PortInfo(port_id,port_name,neutron_port.tenant_id,
                            neutron_port.network_id, neutron_port.device_id)
                            ports[port_name].UpdateRates(rx, tx)
                    

                
#guarantees = {'tap44e21c13-40':[200,{192.168.1.18:150}], 'tap840158bf-03':[600,{192.168.2.10:500}]}

        return raw_port

def get_flows():
    for port_name in ports:
        tmp = os.popen("ovs-dpctl dump-flows| grep 'in_port(" + ports[port_name].port_id +")'").read()
	print tmp
        for flow in tmp.split("\n"):
            flow_info = flow.split(",")
            flow_dst = ""
            flow_byte = ""
            for info in flow_info:
                if info.startswith("ipv4"):
                    flow_src = info.split("=")[-1]
                    flow_dst = flow_info[(flow_info.index(info) + 1)].split("=")[-1]
                if info.startswith(' bytes'):
                    flow_byte = info.split(":")[-1]
            if flow_dst != "":
                ports[port_name].add_flow(flow_src, flow_dst, flow_byte)      
                print "adding flows from get flow:", flow_dst
        
def get_inflows():
    global ports
    global ip_ports
    cmd = "ovs-dpctl dump-flows| grep 'in_port(" + OUT_PORT +")' | grep 192.168"
    #print cmd
    tmp = os.popen(cmd).read()
    #print tmp
    for flow in tmp.split("\n"):
        flow_info = flow.split(",")
        flow_src = ""
        flow_dst = ""
        flow_byte = ""
        for info in flow_info:
        #get flow src ip and byte info
            if info.startswith("ipv4"):
                flow_src = info.split("=")[-1]
                flow_dst = flow_info[(flow_info.index(info) + 1)].split("=")[-1]
                print "in_flow: src--" + flow_src + "dst--" + flow_dst
            if info.startswith(' bytes'):
                flow_byte = info.split(":")[-1]
        #write new bytes info into port-flow 
        if flow_dst in ip_ports:
            print "flow_stc in ip_ports list"
            dst_port_name = ip_ports[flow_dst]["port_name"] 
            print dst_port_name
            if dst_port_name in ports:
                print "adding flows now!!!"
                ports[dst_port_name].add_in_flow(flow_src, flow_dst, flow_byte)

#######################################################################
   
def main():
    global ports
    flows = []
    x = 0
    get_ports()
    get_flows()
    #print "initing tc"
    #init_tc()
    #print "done tc init"
    while True:
        #getSupression()
#	ts = time.time()
#	st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
#	print st
	for port_id in ports:
	    print port_id
	    port_log=ports[port_id]
	    logging.info('%s,%s', port_id,port_log.tx_rate)
	    for flow_id in port_log.flows:
		print flow_id
		flow_log = port_log.flows[flow_id]
		logging.info('%s,%s', flow_id,flow_log.tx_rate)
	
    #    update_port_caps()
    #    in_flow_feedback()
    #    update_flow_caps()
        x = x + 0.1
        time.sleep(1)

            

if __name__ == '__main__':
    main()

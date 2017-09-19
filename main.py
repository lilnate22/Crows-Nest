from flask import Flask
from flask import request
import logging as log
import yaml
import sys
import boto.route53
import os
from commentModule import comment
from repo_parser import getRepo
from boto.route53.record import ResourceRecordSets
from k8shelpers.kubehelper import kubecluster, createStack, deleteStack
from configParser import ConfigParser
import json


ZONE_ID = os.getenv('CROW_ZONE_ID', None)  # k8s secret later
DNS = os.getenv('CROW_DNS', None)  # need to get from secret later
NODE_IP = os.getenv('CROW_NODE_IP', None)  # need to get from k8s secret later
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
CROW_REGISTRY = os.getenv('CROW_REGISTRY', None)
KUBE_CONF = os.getenv('KUBECONF', None)
CROW_REPO = os.getenv("CROW_REPO", "github")
DNS_TYPE = 'A'
CROW_RAW_REPO = os.getenv("CROW_RAW_REPO", "https://raw.githubusercontent.com")
PROJECT_PORTS = {}

root = log.getLogger()
root.setLevel(log.INFO)

ch = log.StreamHandler(sys.stdout)
ch.setLevel(log.DEBUG)
formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
root.addHandler(ch)

app = Flask(__name__)
conn = boto.route53.connect_to_region(AWS_REGION)


@app.route('/', methods=['POST'])
def main():
    data = request.json
    parsed_data = getRepo(CROW_REPO, data)
    # get the contents of the crowsnest yaml

    # get the project specific params
    configUrl = CROW_RAW_REPO + '/' + parsed_data['image'] + '/'+parsed_data['branch']+ '/crow.yaml'
    config = ConfigParser(configUrl).getConfig()

    port = config['port'] or 8080
    zone = config['zone']
    dns = config['dns']
    ip = config['ip']
    dns_type = config['recordType']


    # set the config params to our variables
    global NODE_IP, DNS, ZONE_ID, DNS_TYPE
    NODE_IP = ip
    DNS = dns
    parsed_data['port'] = port
    ZONE_ID = zone
    DNS_TYPE = dns_type

    parsed_data['url'] = parsed_data['branch'] + '.' + DNS

    if parsed_data['action'] == 'opened' or parsed_data['action'] == 'reopened':
        log.info('PR opened, creating DNS records + k8s deploy for branch' + parsed_data['branch'])
        opened(parsed_data['branch'], parsed_data['image'], parsed_data['port'])
        comment(parsed_data)
    elif parsed_data['action'] == 'closed':
        log.info('PR closed, deleting DNS records + k8s deploy for branch' + parsed_data['branch'])
        closed(parsed_data['branch'], parsed_data['port'])
    elif parsed_data['action'] == 'updated':
        log.info('PR has been updated, updating deployment' + parsed_data['branch'])
    return 'OK'


def opened(branch, image, port=8080):
    '''
     We will 1st need to create a deployment with branch image
     then we will need to create a svc for it + ingress rules
     finally create a r53 record
    '''
    change_set = ResourceRecordSets(conn, ZONE_ID)
    changes1 = change_set.add_change("UPSERT", branch + '.' + DNS, type=DNS_TYPE, ttl=60)
    changes1.add_value(NODE_IP)
    change_set.commit()
    # need to change the pod stuff to be a bit more dynamic...
    pod = {
        "name": branch,
        "host": branch + '.' + DNS,
        "port": port
    }

    if (CROW_REGISTRY == None):
        pod['image'] = image + ':' + branch
    else:
        pod['image'] = CROW_REGISTRY + image + ':' + branch
    # runs through the create stack process
    createStack(pod, KUBE_CONF)


def closed(branch, port=8080):
    '''
    We will need to get ingress, and then remove the ingress rule for this dns.
    delete deployments from this branch, as well as remove r53 record
    '''
    change_set = ResourceRecordSets(conn, ZONE_ID)
    changes1 = change_set.add_change("DELETE", branch + '.' + DNS, type="A", ttl=60)
    changes1.add_value(NODE_IP)
    change_set.commit()

    pod = {
        "name": branch,
        "image": 'none',  # dont need image here for deletion
        "host": branch + '.' + DNS,
        "port": port
    }

    # runs through the create stack process
    deleteStack(pod, KUBE_CONF)


@app.route('/healthCheck')
def healthz():
    return "OK"


@app.route('/getProjects')
def getProjects():
    return json.dumps(PROJECT_PORTS)


@app.route('/setProjects', methods=['POST'])
def setProjects():
    data = request.json
    PROJECT_PORTS.update(data)
    return json.dumps(PROJECT_PORTS)


if __name__ == "__main__":
    app.run(host='0.0.0.0')
    log.info('Crows Nest Running')

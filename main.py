from flask import Flask
from flask import request
import logging as log
import sys
import boto.route53
import os
from commentModule import comment
from repo_parser import getRepo
from boto.route53.record import ResourceRecordSets
from k8shelpers.kubehelper import kubecluster, createStack, deleteStack

ZONE_ID = os.environ['CROW_ZONE_ID']  # k8s secret later
DNS = os.environ['CROW_DNS']  # need to get from secret later
NODE_IP = os.environ['CROW_NODE_IP']  # need to get from k8s secret later
AWS_REGION = os.getenv('AWS_REGION', 'us-west-2')
CROW_REGISTRY = os.getenv('CROW_REGISTRY', None)
KUBE_CONF = os.getenv('KUBECONF', None)
CROW_REPO = os.getenv("CROW_REPO", "github")


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
    parsed_data['url'] = parsed_data['branch'] + '.' + DNS
    if parsed_data['action'] == 'opened' or parsed_data['action'] == 'reopened':
        log.info('PR opened, creating DNS records + k8s deploy for branch' + parsed_data['branch'])
        opened(parsed_data['branch'], parsed_data['image'])
        comment(parsed_data)
    elif parsed_data['action'] == 'closed':
        log.info('PR closed, deleting DNS records + k8s deploy for branch' + parsed_data['branch'])
        closed(parsed_data['branch'])
    elif parsed_data['action'] == 'updated':
        log.info('PR has been updated, updating deployment' + parsed_data['branch'])
    return 'OK'


def opened(branch, image):
    '''
     We will 1st need to create a deployment with branch image
     then we will need to create a svc for it + ingress rules
     finally create a r53 record
    '''
    change_set = ResourceRecordSets(conn, ZONE_ID)
    changes1 = change_set.add_change("UPSERT", branch + '.' + DNS, type="A", ttl=3000)
    changes1.add_value(NODE_IP)
    change_set.commit()
    # need to change the pod stuff to be a bit more dynamic...
    pod = {
        "name": branch,
        "host": branch + '.' + DNS
    }

    if (CROW_REGISTRY == None):
        pod['image'] = image + ':' + branch
    else:
        pod['image'] = CROW_REGISTRY + image + ':' + branch
    # runs through the create stack process
    createStack(pod, KUBE_CONF)


def closed(branch):
    '''
    We will need to get ingress, and then remove the ingress rule for this dns.
    delete deployments from this branch, as well as remove r53 record
    '''
    change_set = ResourceRecordSets(conn, ZONE_ID)
    changes1 = change_set.add_change("DELETE", branch + '.' + DNS, type="A", ttl=3000)
    changes1.add_value(NODE_IP)
    change_set.commit()

    pod = {
        "name": branch,
        "image": 'none',  # dont need image here for deletion
        "host": branch + '.' + DNS
    }

    # runs through the create stack process
    deleteStack(pod, KUBE_CONF)


@app.route('/healthCheck')
def healthz():
    return "OK"


@app.route('/getProjects')
def getProjects():
    return 'OK'


if __name__ == "__main__":
    app.run(host='0.0.0.0')
    log.info('Crows Nest Running')

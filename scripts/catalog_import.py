"""Admin-only JSON catalog import; entries always enter the pending review queue."""
import argparse
import json
import os
from urllib.request import Request,urlopen

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('file')
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    token=os.environ['FLOWRANK_ADMIN_TOKEN']
    with open(args.file) as source:
        data=json.load(source)
    req=Request(args.base_url+'/api/admin/catalog',data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','X-FlowRank':'1'})
    with urlopen(req,timeout=30) as response:
        print(response.status,response.read().decode())

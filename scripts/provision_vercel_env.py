"""Operator helper: stream credentials to the CLI without shell interpolation."""
import hashlib
import json
import secrets
import subprocess
from pathlib import Path

if __name__=='__main__':
    credentials=json.loads(Path('.local/credentials.json').read_text())
    if 'cron_secret' not in credentials:
        credentials['cron_secret']=secrets.token_urlsafe(40)
        Path('.local/credentials.json').write_text(json.dumps(credentials))
    values={'DATABASE_URL':Path('.local/database-url').read_text().strip(),
            'COOKIE_SECURE':'true',
            'ADMIN_TOKEN_HASH':hashlib.sha256(credentials['admin_token'].encode()).hexdigest(),
            'CRON_SECRET':credentials['cron_secret']}
    for name,value in values.items():
        # Raw API avoids CLI client-encrypted envelopes on incompatible env endpoints.
        command=['node','.local/cli/node_modules/vercel/dist/index.js','api',
                 '/v10/projects/prj_pyDR8VWJdYmQLoieW8RlkS4bEyIl/env?teamId=team_o7WjUHworZZFhCey09szx4Uw&upsert=true',
                 '--method','POST','--input','-','--scope','vamshi-krishnas-projects-861bffd9']
        payload={'key':name,'value':value,'target':['production'],'type':'plain' if name=='COOKIE_SECURE' else 'sensitive'}
        result=subprocess.run(command,input=json.dumps(payload),text=True,capture_output=True)
        print(name+': '+('saved' if result.returncode==0 else 'failed'))
        if result.returncode:
            # CLI errors do not print the streamed value; still emit only a bounded diagnostic.
            print(result.stderr[-1500:])
            raise SystemExit(result.returncode)

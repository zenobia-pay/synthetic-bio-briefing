#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, time, urllib.request
from pathlib import Path
BASE='https://api.browser-use.com/api/v2'
PROFILE='9e0f01a3-5227-4424-bc58-b9b226110020'

def req(api_key, method, path, payload=None):
 data=None if payload is None else json.dumps(payload).encode('utf-8')
 r=urllib.request.Request(BASE+path,data=data,method=method,headers={'Content-Type':'application/json','X-Browser-Use-API-Key':api_key})
 with urllib.request.urlopen(r,timeout=120) as x:
  return json.loads(x.read().decode('utf-8'))

def run(api_key,prompt,timeout):
 s=req(api_key,'POST','/sessions',{'profileId':PROFILE,'persistMemory':True,'keepAlive':False})
 t=req(api_key,'POST','/tasks',{'task':prompt,'sessionId':s['id']})
 start=time.time(); st=None
 while time.time()-start<timeout:
  st=req(api_key,'GET',f"/tasks/{t['id']}/status")
  if st.get('status') in ('finished','failed','stopped'): break
  time.sleep(8)
 return {'session':s,'task':t,'status':st}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--query',required=True); ap.add_argument('--out',required=True); ap.add_argument('--timeout',type=int,default=900)
 a=ap.parse_args(); key=os.environ.get('BROWSER_USE_API_KEY')
 if not key: raise SystemExit('Missing BROWSER_USE_API_KEY')
 payload=run(key,a.query,a.timeout)
 out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps({'query':a.query,**payload},indent=2))
 print(out)

if __name__=='__main__': main()

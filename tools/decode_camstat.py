import json,pathlib,struct,hashlib
schema=json.loads(pathlib.Path(__file__).with_name('camstat_schema.json').read_text())
class Reader:
 def __init__(self,b):self.b=b;self.p=0
 def u(self):
  n=s=0
  while True:
   c=self.b[self.p];self.p+=1;n|=(c&127)<<s;s+=7
   if c<128:return n
 def read(self,t):
  if isinstance(t,list):return [self.read(t[0]) for _ in range(self.u())]
  if t in ('n','v'):return self.u()
  if t=='q':
   tag=self.u()
   if tag==0:return self.u()
   assert tag==1,tag
   v=struct.unpack_from('<d',self.b,self.p)[0];self.p+=8;return v
  if t=='i':
   n=self.u();return (n>>1)^-(n&1)
  if t=='b':v=self.b[self.p];self.p+=1;assert v<2;return bool(v)
  if t=='h':v=self.b[self.p:self.p+32].hex();self.p+=32;return v
  if t=='f':v=struct.unpack_from('<d',self.b,self.p)[0];self.p+=8;return v
  size=self.u();end=self.p+size
  v={k:self.read(ft) for k,ft in schema['types'][t]};assert self.p==end,(t,self.p,end);return v

def decode(path):
 b=pathlib.Path(path).read_bytes()
 if len(b)<64 or b[:8]!=b'CAMSTAT\0':raise ValueError('Invalid CAMSTAT header')
 version,flags=struct.unpack_from('<II',b,8)
 if version!=1 or flags!=0:raise ValueError('Unsupported CAMSTAT version/flags')
 if struct.unpack_from('<QQ',b,16)!=(len(b)-64,)*2:raise ValueError('Invalid CAMSTAT length')
 if hashlib.sha256(b[64:]).digest()!=b[32:64]:raise ValueError('CAMSTAT checksum mismatch')
 r=Reader(b[64:]);out={}
 while r.p<len(r.b):
  sid=r.u();version=r.u()
  if version!=1:raise ValueError('Unsupported section version')
  size=r.u();end=r.p+size
  _,name,t=next(x for x in schema['sections'] if x[0]==sid)
  if name in out:raise ValueError('Duplicate section')
  out[name]=r.read(t)
  if r.p!=end:raise ValueError('Section length mismatch')
 return out

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description='Decode CAMSTAT v1 locally using the official toolkit schema.')
 parser.add_argument('input',type=pathlib.Path);parser.add_argument('output',type=pathlib.Path)
 args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
 paths=sorted(args.input.glob('*.camstat')) if args.input.is_dir() else [args.input]
 for file in paths:
  data=decode(file);(args.output/(file.stem+'.json')).write_text(json.dumps(data,indent=2))
  print(file.name,data['match']['roundsStarted'],[x['submittedGems'] for x in data['teams']])

#!/usr/bin/env python3
"""Generate our own closed, UV-textured 24 x 8 x 12 mm colour test block.

No third-party model assets. RGB texture deliberately mixes the four default
PLA swatches; it is a pipeline fixture, not a calibrated optical standard.
"""
import json
from pathlib import Path
import struct
import sys
import zlib


def make(path, stripes=None):
    vertices = [(0,0,0),(24,0,0),(24,8,0),(0,8,0),(0,0,12),(24,0,12),(24,8,12),(0,8,12)]
    quads = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    positions, uv, indices = [], [], []
    for q in quads:
        start = len(positions)
        positions.extend(vertices[i] for i in q)
        uv.extend([(0,0),(1,0),(1,1),(0,1)])
        indices.extend([start,start+1,start+2,start,start+2,start+3])
    colors = [(245,234,208),(38,38,38),(243,107,33),(0,134,214)]
    rows = []
    for y in range(32):
        row = bytearray([0])
        for x in range(64):
            u, v = x/63, y/31
            if stripes:
                row.extend(stripes[min(len(stripes)-1, x*len(stripes)//64)])
            else:
                row.extend(round((1-v)*((1-u)*colors[0][c]+u*colors[2][c])+v*((1-u)*colors[3][c]+u*colors[1][c])) for c in range(3))
        rows.append(row)
    def chunk(tag, data):
        return struct.pack('>I', len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,32,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
    binary = bytearray()
    views = []
    def add(data):
        while len(binary)%4:
            binary.append(0)
        views.append({'buffer':0,'byteOffset':len(binary),'byteLength':len(data)})
        binary.extend(data)
        return len(views)-1
    pos = add(struct.pack('<'+'f'*len(positions)*3,*(v for p in positions for v in p)))
    tex = add(struct.pack('<'+'f'*len(uv)*2,*(v for p in uv for v in p)))
    ind = add(struct.pack('<'+'H'*len(indices),*indices))
    img = add(png)
    doc = {'asset':{'version':'2.0','generator':'DitherForge INDX test fixture'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0}],
           'meshes':[{'primitives':[{'attributes':{'POSITION':0,'TEXCOORD_0':1},'indices':2,'material':0}]}],
           'materials':[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0},'metallicFactor':0,'roughnessFactor':1}}],
           'textures':[{'source':0}], 'images':[{'bufferView':img,'mimeType':'image/png'}],
           'accessors':[{'bufferView':pos,'componentType':5126,'count':len(positions),'type':'VEC3','min':[0,0,0],'max':[24,8,12]},
                        {'bufferView':tex,'componentType':5126,'count':len(uv),'type':'VEC2'},
                        {'bufferView':ind,'componentType':5123,'count':len(indices),'type':'SCALAR'}],
           'bufferViews':views,'buffers':[{'byteLength':len(binary)}]}
    js = json.dumps(doc,separators=(',',':')).encode()
    js += b' '*((-len(js))%4)
    binary += b'\0'*((-len(binary))%4)
    total = 12+8+len(js)+8+len(binary)
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_bytes(struct.pack('<III',0x46546c67,2,total)+struct.pack('<II',len(js),0x4e4f534a)+js+struct.pack('<II',len(binary),0x004e4942)+binary)


if __name__ == '__main__':
    make(sys.argv[1])

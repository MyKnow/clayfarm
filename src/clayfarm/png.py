"""Small dependency-free PNG utility for RGB/RGBA8 Blender previews (not general images)."""
from __future__ import annotations
import struct
import zlib
from pathlib import Path
from .util import FarmError, atomic_bytes


def encode(width: int, height: int, rgba: bytes) -> bytes:
    if width < 1 or height < 1 or len(rgba) != width * height * 4:
        raise FarmError("Invalid RGBA buffer")
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    raw = b"".join(b"\0" + rgba[y*width*4:(y+1)*width*4] for y in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width,height,8,6,0,0,0)) + chunk(b"IDAT",zlib.compress(raw)) + chunk(b"IEND",b"")


def decode(data: bytes) -> tuple[int, int, bytes]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise FarmError("Expected PNG preview")
    p, compressed, header = 8, bytearray(), None
    while p + 12 <= len(data):
        n = struct.unpack(">I",data[p:p+4])[0]
        tag = data[p+4:p+8]; block = data[p+8:p+8+n]
        if len(block) != n or p + 12 + n > len(data):
            raise FarmError("Truncated PNG")
        if zlib.crc32(tag+block) & 0xffffffff != struct.unpack(">I",data[p+8+n:p+12+n])[0]:
            raise FarmError("PNG checksum mismatch")
        if tag == b"IHDR": header=struct.unpack(">IIBBBBB",block)
        elif tag == b"IDAT": compressed.extend(block)
        elif tag == b"IEND": break
        p += n+12
    if header is None:
        raise FarmError("Missing PNG header")
    w,h,depth,typ,comp,filt,interlace=header
    if depth!=8 or typ not in (2,6) or interlace or comp or filt or not 1<=w<=4096 or not 1<=h<=4096:
        raise FarmError("Only non-interlaced RGB/RGBA8 previews up to 4096 pixels are supported")
    bpp=4 if typ==6 else 3; stride=w*bpp
    expected=(stride+1)*h
    dec=zlib.decompressobj(); raw=dec.decompress(bytes(compressed),expected+1)
    if len(raw)!=expected or not dec.eof:
        raise FarmError("PNG decompressed length mismatch")
    previous=bytearray(stride); rgba=bytearray(w*h*4)
    def paeth(a,b,c):
        pred=a+b-c; da,db,dc=abs(pred-a),abs(pred-b),abs(pred-c)
        return a if da<=db and da<=dc else b if db<=dc else c
    for y in range(h):
        kind=raw[y*(stride+1)]; row=bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        if kind>4: raise FarmError("Unsupported PNG filter")
        for x in range(stride):
            a=row[x-bpp] if x>=bpp else 0; b=previous[x]; c=previous[x-bpp] if x>=bpp else 0
            v=0 if kind==0 else a if kind==1 else b if kind==2 else (a+b)//2 if kind==3 else paeth(a,b,c)
            row[x]=(row[x]+v)&255
        for x in range(w):
            i=(y*w+x)*4; s=x*bpp
            rgba[i:i+4]=row[s:s+3]+bytes([row[s+3] if bpp==4 else 255])
        previous=row
    return w,h,bytes(rgba)


def contact_sheet(rows: list[list[Path]], output: Path, tile: int = 256, labels=None) -> None:
    if not rows: raise FarmError("No finished previews yet")
    cols=max(map(len,rows)); w,h=cols*tile,len(rows)*tile
    if w>4096 or h>4096: raise FarmError("Too many preview tiles")
    canvas=bytearray([235,235,235,255])*(w*h)
    for ri,row in enumerate(rows):
        for ci,path in enumerate(row):
            iw,ih,src=decode(path.read_bytes())
            ratio=min(tile/iw,tile/ih); tw,th=max(1,int(iw*ratio)),max(1,int(ih*ratio))
            dx,dy=ci*tile+(tile-tw)//2,ri*tile+(tile-th)//2
            for y in range(th):
                sy=min(ih-1,int(y/ratio))
                for x in range(tw):
                    sx=min(iw-1,int(x/ratio)); s=(sy*iw+sx)*4; d=((dy+y)*w+dx+x)*4
                    a=src[s+3]
                    canvas[d:d+4]=bytes([(src[s+k]*a+235*(255-a))//255 for k in range(3)]+[255])
            if labels:
                # Small built-in bitmap font keeps the worker free of image/font packages.
                glyphs={
                    'A':'010101111101101','B':'110101110101110','C':'011100100100011',
                    'D':'110101101101110','E':'111100110100111','F':'111100110100100',
                    'G':'011100101101011','H':'101101111101101','I':'111010010010111',
                    'J':'001001001101010','K':'101101110101101','L':'100100100100111',
                    'M':'101111111101101','N':'101111111111101','O':'010101101101010',
                    'P':'110101110100100','Q':'010101101011001','R':'110101110101101',
                    'S':'011100010001110','T':'111010010010010','U':'101101101101111',
                    'V':'101101101101010','W':'101101111111101','X':'101101010101101',
                    'Y':'101101010010010','Z':'111001010100111','_':'000000000000111'}
                label=labels[ri][ci].upper()[:max(1,(tile-8)//8)]
                for index,char in enumerate(label):
                    for bit,value in enumerate(glyphs.get(char,'0'*15)):
                        if value=='1':
                            for oy in range(2):
                                for ox in range(2):
                                    x=ci*tile+4+index*8+(bit%3)*2+ox
                                    y=ri*tile+4+(bit//3)*2+oy
                                    d=(y*w+x)*4; canvas[d:d+4]=bytes([35,35,35,255])
    atomic_bytes(output,encode(w,h,bytes(canvas)))

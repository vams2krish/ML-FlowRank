"""Generate six original CC0 motion studies, MP4s and posters (authoring only)."""
import math
import subprocess
from pathlib import Path
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter

OUT=Path(__file__).resolve().parents[1]/'static'/'media'
COLORS=[('#246db9','#78f0dd'),('#a3462d','#ffd283'),('#2a747e','#e3c5a1'),('#6838a0','#ffa2d1'),('#648f3b','#e5ff8c'),('#b54374','#97a9ff')]
NAMES=['signal','simmer','horizon','frequency','momentum','color']


def frame(index,t,width=360,height=640):
    a,b=COLORS[index]
    image=Image.new('RGB',(width,height),'#080c18')
    glow=Image.new('RGB',image.size,'#080c18')
    d=ImageDraw.Draw(glow)
    for j in range(6):
        x=width*(.5+.45*math.sin(t*.5+j*1.4+index))
        y=height*(.5+.4*math.cos(t*.4+j+index))
        r=70+j*8
        d.ellipse((x-r,y-r,x+r,y+r),fill=a if j%2 else b)
    image=Image.blend(image,glow.filter(ImageFilter.GaussianBlur(45)),.65)
    d=ImageDraw.Draw(image)
    for j in range(18):
        points=[]
        for x in range(-10,width+10,4):
            y=height*.5+math.sin(x*.015+t+j*.13)*(75+index*10)+math.cos(x*.007-t*.5)*80+(j-9)*11
            points.append((x,y))
        d.line(points,fill=b if j%3==0 else a,width=2)
    d.text((24,38),f'F L O W   S T U D Y   0{index+1}',fill='#ffffff')
    d.text((24,596),'ORIGINAL MOTION / FLOWRANK',fill='#dddddd')
    return image


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    for index,name in enumerate(NAMES):
        frame(index,0).save(OUT/f'{name}.jpg',quality=88)
        process=subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-f','rawvideo','-vcodec','rawvideo','-s','360x640','-pix_fmt','rgb24','-r','20','-i','-','-an','-vcodec','libx264','-preset','fast','-crf','27','-pix_fmt','yuv420p','-movflags','+faststart',str(OUT/f'{name}.mp4')],stdin=subprocess.PIPE,stderr=subprocess.DEVNULL)
        for n in range(240):
            process.stdin.write(frame(index,n/20).tobytes())
        process.stdin.close()
        if process.wait()!=0:
            raise RuntimeError('Video encoding failed')
        print(name,flush=True)

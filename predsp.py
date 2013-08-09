#!/usr/bin/python

# This script works together with 'fcdpp-server.py -p' to move data
# preprocessing from fcdpp-server to the host running dspserver.

import sys, socket, struct, numpy

BUFFER_SIZE = 1024 # from dspserver
TXLEN = 500 # from dspserver
PTXLEN = 1024 # for predsp
PORT = 13000

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8*1024**2)
sock.bind(('0.0.0.0', PORT+500))

wsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
wsock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8*1024**2)

if '-s' in sys.argv:
	swapiq = True
else:
	swapiq = False

buff = ''
seq = -1L
nseq = 0L
while 1:
	data, addr = sock.recvfrom(PTXLEN*2)
	if len(data)!=PTXLEN+4:
		print 'Bad packet size!!!'
		continue
	pseq = struct.unpack('<I', data[:4])[0]
	if seq>=0 and seq<pseq:
		pseq = struct.unpack('<I', data[:4])[0]
		buff += '\0'*(pseq-seq-1)*PTXLEN
	else:
		seq = pseq
	buff += data[4:]
	if len(buff)>=BUFFER_SIZE*4:
		naudio = numpy.fromstring(buff, dtype="<h")/numpy.float32(32767.0)
		naudio.resize(len(naudio)/(BUFFER_SIZE*2), BUFFER_SIZE*2)
		for i in naudio:
			if swapiq:
				txdata = i[::2].tostring() + i[1::2].tostring()
			else:
				txdata = i[1::2].tostring() + i[::2].tostring()
			for j in xrange(0, (len(txdata)+TXLEN-1)/(TXLEN)):
				snd = struct.pack('<IIHH', nseq&0xFFFFFFFF, (nseq>>32)&0xFFFFFFFF, j*TXLEN, min(len(txdata)-j*TXLEN, TXLEN))
				wsock.sendto(snd+txdata[j*TXLEN:j*TXLEN+min(len(txdata)-j*TXLEN, TXLEN)], ('127.0.0.1', PORT))
			nseq += 1
		buff = ''


#!/usr/bin/python

import threading, SocketServer, alsaaudio, socket, time, re, sys, struct, os, hid

CMDLEN = 1024 # should always fit
BUFFER_SIZE = 1024 # from dspserver
PERIOD = 1024 # BUFFER_SIZE*4/N, N=4
TXLEN = 500 # from dspserver

class SharedData(object):
	def __init__(self, *args, **kwargs):
		self.mutex = threading.Lock()
		self.clients = {}
		self.receivers = {}

	def acquire(self):
		self.mutex.acquire()

	def release(self):
		self.mutex.release()

class ConnectedClient(object):
	def __init__(self, *args, **kwargs):
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
		self.receiver = -1
		self.port = -1

class Listener(SocketServer.ThreadingTCPServer):
	def __init__(self, server_address, RequestHandlerClass, shared):
		SocketServer.ThreadingTCPServer.__init__(self, server_address, RequestHandlerClass)
		self.shared = shared

class ListenerHandler(SocketServer.BaseRequestHandler):
	def handle(self):
		caddr = self.client_address
		shared = self.server.shared
		shared.acquire()
		shared.clients[caddr] = ConnectedClient()
		shared.release()
		while 1:
			try:
				data = self.request.recv(CMDLEN)
			except:
				break
			if not data:
				break
			m = re.search('^attach (\d+)', data, re.M)
			if m:
				shared.acquire()
				if shared.clients[caddr].receiver!=-1:
					shared.release()
					self.request.sendall('Error: Client is already attached to receiver')
					continue
				if int(m.group(1)) not in shared.receivers.keys():
					shared.release()
					self.request.sendall('Error: Invalid Receiver')
					continue
				if int(m.group(1)) in [shared.clients[i].receiver for i in shared.clients.keys()]:
					shared.release()
					self.request.sendall('Error: Receiver in use')
					continue
				shared.clients[caddr].receiver = int(m.group(1))
				shared.release()
				self.request.sendall('OK 192000')
				continue
			m = re.search('^detach (\d+)', data, re.M)
			if m:
				shared.acquire()
				if shared.clients[caddr].receiver==-1:
					shared.release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				if shared.clients[caddr].receiver!=int(m.group(1)):
					shared.release()
					self.request.sendall('Error: Invalid Receiver')
					continue
				shared.clients[caddr].receiver = -1
				shared.clients[caddr].port = -1
				shared.release()
				self.request.sendall('OK 192000')
				continue
			m = re.search('^frequency ([0-9.,e+-]+)', data, re.M)
			if m:
				shared.acquire()
				if shared.clients[caddr].receiver==-1:
					shared.release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				idx = shared.clients[caddr].receiver
				cd = shared.receivers[idx]
				shared.release()
				try:
					freq = int(m.group(1))
					setfreq(cd, freq)
				except:
					self.request.sendall('Error: Invalid frequency')
					continue
				self.request.sendall('OK')
				continue
			m = re.search('^start (iq|bandscope) (\d+)', data, re.M)
			if m:
				shared.acquire()
				if shared.clients[caddr].receiver==-1:
					shared.release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				if m.group(1)=='iq':
					shared.clients[caddr].port = int(m.group(2))
				shared.release()
				self.request.sendall('OK')
				continue
			m = re.search('^stop (iq|bandscope)', data, re.M)
			if m:
				shared.acquire()
				if shared.clients[caddr].receiver==-1:
					shared.release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				if m.group(1)=='iq':
					if shared.clients[caddr].port==-1:
						shared.release()
						self.request.sendall('Error: Client is not started')
						continue
					shared.clients[caddr].port = -1
				shared.release()
				self.request.sendall('OK')
				continue
			#m = re.search('^hardware\?', data, re.M)
			#if m:
			#	self.request.sendall('OK fcdproplus')
			#	continue
			self.request.sendall('Error: Invalid Command')
		shared.acquire()
		shared.clients.pop(caddr)
		shared.release()

def listener(h, p, c):
	server = Listener((h, p), ListenerHandler, c)
	server.serve_forever()

def create_listener_thread(h, p):
	c = SharedData()
	t = threading.Thread(target=listener, args=(h, p, c))
	t.start()
	return (c, t)

def short2float(inp, offset):
	data = [struct.unpack('h', inp[i*4+offset:i*4+offset+2])[0] for i in xrange(0, len(inp)/4)]
	data = [struct.pack('f', i/32767.0) for i in data]
	data = ''.join(data)
	return data

def fcdproplus_io(shared, ad, cd, swapiq, idx):
	fcdpp_init(cd)
	shared.acquire()
	if idx in shared.receivers.keys():
		shared.release()
		raise IOError, 'Receiver with inde %d already connected' % (idx)
	shared.receivers[idx] = cd
	shared.release()
	pcm = alsaaudio.PCM(type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NORMAL, card=ad)
	pcm.setchannels(2)
	pcm.setrate(192000)
	pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
	pcm.setperiodsize(PERIOD)
	seq = 0L
	while 1:
		length, audio = pcm.read()
		rcv = []
		shared.acquire()
		for caddr in shared.clients.keys():
			if shared.clients[caddr].receiver==idx and shared.clients[caddr].port!=-1:
				rcv.append((shared.clients[caddr].socket, (caddr[0], shared.clients[caddr].port)))
		shared.release()
		for i in xrange(0, len(audio)/(4*BUFFER_SIZE)):
			if swapiq:
				txdata = short2float(audio[i*BUFFER_SIZE*4:(i+1)*BUFFER_SIZE*4], 2) + short2float(audio[i*BUFFER_SIZE*4:(i+1)*BUFFER_SIZE*4], 0) 
			else:
				txdata = short2float(audio[i*BUFFER_SIZE*4:(i+1)*BUFFER_SIZE*4], 0) + short2float(audio[i*BUFFER_SIZE*4:(i+1)*BUFFER_SIZE*4], 2) 
			for j in xrange(0, (len(txdata)+TXLEN-1)/(TXLEN)):
				for k in rcv:
					snd = struct.pack('LHH', seq, j*TXLEN, min(len(txdata)-j*TXLEN, TXLEN))
					k[0].sendto(snd+txdata[j*TXLEN:j*TXLEN+min(len(txdata)-j*TXLEN, TXLEN)], k[1])
			seq += 1

def autodetect_ad():
	try:
		return 'hw:%s' % (alsaaudio.cards().index('V20'))
	except:
		return None

def autodetect_cd():
	return (0x04d8, 0xfb31)

def setfreq(cd, freq):
	d = apply(hid.device, cd)
	d.write([0, 101] + map(ord, struct.pack('I', freq)))
	if d.read(65)[0]!=101:
		raise IOError, 'Cant set freq'
	d.close()

def fcdpp_init(cd):
	d = apply(hid.device, cd)
	#get ver
	d.write([0,1])
	ver = d.read(65)[2:15]
	#set lna
	d.write([0, 110, 1])
	if d.read(65)[0]!=110:
		raise IOError, 'Cant set lna gain'
	#set mixer gain
	d.write([0, 114, 1])
	if d.read(65)[0]!=114:
		raise IOError, 'Cant set mixer gain'
	#set if gain
	d.write([0, 117, 0])
	if d.read(65)[0]!=117:
		raise IOError, 'Cant set mixer gain'
	d.close()

def create_fcdproplus_thread(clients, ad=autodetect_ad(), cd=autodetect_cd(), swapiq=None, idx=0):
	if not ad:
		raise IOError, 'Audio device not found'
	t = threading.Thread(target=fcdproplus_io, args=(clients, ad, cd, swapiq, idx))
	t.start()
	return (ad, cd, idx, t)

shared, lt = create_listener_thread('0.0.0.0', 11000)
ad, cd, idx, ft = create_fcdproplus_thread(shared, swapiq='-s' in sys.argv)

try:
	while 1:
		time.sleep(1)
except KeyboardInterrupt:
	print 'exiting...'
	os.kill(os.getpid(), 15)


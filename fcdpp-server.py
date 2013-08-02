#!/usr/bin/python

import threading, SocketServer, alsaaudio, socket, time, re, sys, struct, os, hid

CMDLEN = 1024 # should always fit
BUFFER_SIZE = 1024 # from dspserver
PERIOD = 1024 # BUFFER_SIZE*4/N, N=4
TXLEN = 500 # from dspserver

class Listener(SocketServer.ThreadingTCPServer):
	def __init__(self, server_address, RequestHandlerClass, clients):
		SocketServer.ThreadingTCPServer.__init__(self, server_address, RequestHandlerClass)
		self.clients = clients

class ListenerHandler(SocketServer.BaseRequestHandler):
	def handle(self):
		self.server.clients[0].acquire()
		self.server.clients[1][self.client_address] = [-1, -1, -1]
		self.server.clients[0].release()
		while 1:
			try:
				data = self.request.recv(CMDLEN)
			except:
				break
			if not data:
				break
			m = re.search('^attach (\d+)', data, re.M)
			if m:
				self.server.clients[0].acquire()
				if self.server.clients[1][self.client_address][0]!=-1:
					self.server.clients[0].release()
					self.request.sendall('Error: Client is already attached to receiver')
					continue
				if int(m.group(1)) not in self.server.clients[2].keys():
					self.server.clients[0].release()
					self.request.sendall('Error: Invalid Receiver')
					continue
				if int(m.group(1)) in [i[0] for i in self.server.clients[1]]:
					self.server.clients[0].release()
					self.request.sendall('Error: Receiver in use')
					continue
				self.server.clients[1][self.client_address] = [int(m.group(1)), socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP), -1]
				self.server.clients[0].release()
				self.request.sendall('OK 192000')
				continue
			m = re.search('^detach (\d+)', data, re.M)
			if m:
				self.server.clients[0].acquire()
				if self.server.clients[1][self.client_address][0]==-1:
					self.server.clients[0].release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				if self.server.clients[1][self.client_address][0]!=int(m.group(1)):
					self.server.clients[0].release()
					self.request.sendall('Error: Invalid Receiver')
					continue
				self.server.clients[1][self.client_address] = [-1, -1, -1]
				self.server.clients[0].release()
				self.request.sendall('OK 192000')
				continue
			m = re.search('^frequency ([0-9.,e+-]+)', data, re.M)
			if m:
				self.server.clients[0].acquire()
				if self.server.clients[1][self.client_address][0]==-1:
					self.server.clients[0].release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				idx = self.server.clients[1][self.client_address][0]
				cd = self.server.clients[2][idx]
				self.server.clients[0].release()
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
				self.server.clients[0].acquire()
				if self.server.clients[1][self.client_address][0]==-1:
					self.server.clients[0].release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				if m.group(1)=='iq':
					self.server.clients[1][self.client_address][2] = int(m.group(2))
				self.server.clients[0].release()
				self.request.sendall('OK')
				continue
			m = re.search('^stop (iq|bandscope)', data, re.M)
			if m:
				self.server.clients[0].acquire()
				if self.server.clients[1][self.client_address][0]==-1:
					self.server.clients[0].release()
					self.request.sendall('Error: Client is not attached to receiver')
					continue
				if m.group(1)=='iq':
					if self.server.clients[1][self.client_address][2]==-1:
						self.server.clients[0].release()
						self.request.sendall('Error: Client is not started')
						continue
					self.server.clients[1][self.client_address][2] = -1
				self.server.clients[0].release()
				self.request.sendall('OK')
				continue
			#m = re.search('^hardware\?', data, re.M)
			#if m:
			#	self.request.sendall('OK fcdproplus')
			#	continue
			self.request.sendall('Error: Invalid Command')
		self.server.clients[0].acquire()
		self.server.clients[1].pop(self.client_address)
		self.server.clients[0].release()

def listener(h, p, c):
	server = Listener((h, p), ListenerHandler, c)
	server.serve_forever()

def create_listener_thread(h, p):
	c = (threading.Lock(), {}, {})
	t = threading.Thread(target=listener, args=(h, p, c))
	t.start()
	return (c, t)

def short2float(inp, offset):
	data = [struct.unpack('h', inp[i*4+offset:i*4+offset+2])[0] for i in xrange(0, len(inp)/4)]
	data = [struct.pack('f', i/32767.0) for i in data]
	data = ''.join(data)
	return data

def fcdproplus_io(clients, ad, cd, idx):
	fcdpp_init(cd)
	clients[0].acquire()
	if idx in clients[2].keys():
		clients[0].release()
		raise IOError, 'Receiver with inde %d already connected' % (idx)
	clients[2][idx] = cd
	clients[0].release()
	pcm = alsaaudio.PCM(type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NORMAL, card=ad)
	pcm.setchannels(2)
	pcm.setrate(192000)
	pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
	pcm.setperiodsize(PERIOD)
	clients[0].acquire()
	clients[0].release()
	seq = 0L
	while 1:
		length, data = pcm.read()
		rcv = []
		clients[0].acquire()
		for i in clients[1].keys():
			if clients[1][i][0]==idx and clients[1][i][2]!=-1:
				rcv.append((clients[1][i][1], (i[0], clients[1][i][2])))
		clients[0].release()
		for i in xrange(0, len(data)/(4*BUFFER_SIZE)):
			txdata = short2float(data[i*BUFFER_SIZE*4:(i+1)*BUFFER_SIZE*4], 0) + short2float(data[i*BUFFER_SIZE*4:(i+1)*BUFFER_SIZE*4], 2) 
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

def create_fcdproplus_thread(clients, ad=autodetect_ad(), cd=autodetect_cd(), idx=0):
	if not ad:
		raise IOError, 'Audio device not found'
	t = threading.Thread(target=fcdproplus_io, args=(clients, ad, cd, idx))
	t.start()
	return (ad, cd, idx, t)

clients, lt = create_listener_thread('0.0.0.0', 11000)
ad, cd, idx, ft = create_fcdproplus_thread(clients)

try:
	while 1:
		time.sleep(1)
except KeyboardInterrupt:
	print 'exiting...'
	os.kill(os.getpid(), 15)


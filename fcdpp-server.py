#!/usr/bin/python

import threading, SocketServer, alsaaudio, socket, time, re, sys, struct, os, hid, numpy

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

class FCDProPlus(object):
	def __init__(self, ad=None, cd=None, swapiq=None, lna_gain=True, mixer_gain=True, if_gain=0, init_freq=7000000):
		self.ad = ad
		if not self.ad:
			self.ad = self.autodetect_ad()
		self.cd = cd
		if not self.cd:
			self.cd = self.autodetect_cd()
		if not self.ad or not self.cd:
			raise IOError, 'FCDPro+ device not found'
		self.swapiq = swapiq

		self.ver = self.get_fw_ver()
		self.set_lna_gain(lna_gain)
		self.set_mixer_gain(mixer_gain)
		self.set_if_gain(if_gain)
		self.set_freq(init_freq)

	def autodetect_ad(self):
		try:
			return 'hw:%s' % (alsaaudio.cards().index('V20'))
		except:
			return None

	def autodetect_cd(self):
		return (0x04d8, 0xfb31)

	def get_fw_ver(self):
		d = apply(hid.device, self.cd)
		d.write([0,1])
		ver = d.read(65)[2:15]
		d.close()
		return ver

	def set_lna_gain(self, lna_gain):
		d = apply(hid.device, self.cd)
		d.write([0, 110, int(bool(lna_gain))])
		if d.read(65)[0]!=110:
			raise IOError, 'Cant set lna gain'
		d.close()

	def set_mixer_gain(self, mixer_gain):
		d = apply(hid.device, self.cd)
		d.write([0, 114, int(bool(mixer_gain))])
		if d.read(65)[0]!=114:
			raise IOError, 'Cant set mixer gain'
		d.close()

	def set_if_gain(self, if_gain):
		d = apply(hid.device, self.cd)
		d.write([0, 117, if_gain])
		if d.read(65)[0]!=117:
			raise IOError, 'Cant set if gain'
		d.close()

	def set_freq(self, freq):
		d = apply(hid.device, self.cd)
		d.write([0, 101] + map(ord, struct.pack('I', freq)))
		if d.read(65)[0]!=101:
			raise IOError, 'Cant set freq'
		d.close()

	def get_pcm(self, period=1024):
		pcm = alsaaudio.PCM(type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NORMAL, card=self.ad)
		pcm.setchannels(2)
		pcm.setrate(192000)
		pcm.setformat(alsaaudio.PCM_FORMAT_S16_LE)
		pcm.setperiodsize(period)
		return pcm

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
				fcd = shared.receivers[idx]
				shared.release()
				try:
					freq = int(m.group(1))
					fcd.set_freq(freq)
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

def fcdproplus_io(shared, fcd, idx):
	shared.acquire()
	if idx in shared.receivers.keys():
		shared.release()
		raise IOError, 'Receiver with inde %d already connected' % (idx)
	shared.receivers[idx] = fcd
	shared.release()
	pcm = fcd.get_pcm(PERIOD)
	seq = 0L
	while 1:
		length, audio = pcm.read()
		rcv = []
		shared.acquire()
		for caddr in shared.clients.keys():
			if shared.clients[caddr].receiver==idx and shared.clients[caddr].port!=-1:
				rcv.append((shared.clients[caddr].socket, (caddr[0], shared.clients[caddr].port)))
		shared.release()
		naudio = numpy.fromstring(audio, dtype="<h")/numpy.float32(32767.0)
		naudio.resize(len(naudio)/(BUFFER_SIZE*2), BUFFER_SIZE*2)
		for i in naudio:
			if fcd.swapiq:
				txdata = i[::2].tostring() + i[1::2].tostring()
			else:
				txdata = i[1::2].tostring() + i[::2].tostring()
			for j in xrange(0, (len(txdata)+TXLEN-1)/(TXLEN)):
				for k in rcv:
					snd = struct.pack('LHH', seq, j*TXLEN, min(len(txdata)-j*TXLEN, TXLEN))
					k[0].sendto(snd+txdata[j*TXLEN:j*TXLEN+min(len(txdata)-j*TXLEN, TXLEN)], k[1])
			seq += 1

def create_fcdproplus_thread(clients, fcd, idx=0):
	t = threading.Thread(target=fcdproplus_io, args=(clients, fcd, idx))
	t.start()
	return (idx, t)

shared, lt = create_listener_thread('0.0.0.0', 11000)
fcd = FCDProPlus(swapiq='-s' in sys.argv)
idx, ft = create_fcdproplus_thread(shared, fcd)

try:
	while 1:
		time.sleep(1)
except KeyboardInterrupt:
	print 'exiting...'
	os.kill(os.getpid(), 15)


ghpsdr3-fcdproplus-server
=========================

It is Funcube Dongle Pro Plus server for ghpsdr3-alex implementation on python.

Dependencies is:
 - python-alsaaudio
 - python-numpy
 - https://github.com/bazuchan/cython-hidapi (fork of https://github.com/gbishop/cython-hidapi)

Todo:
 - support for multiple receivers (it's incomplete).

Basic usage:
 - run fcdpp-server.py
 - run dspserver
 - run QtRadio

Usage: fcdpp-server.py [-h] [-s] [-p] [-l] [-m] [-i IF_GAIN] [-o PPM_OFFSET]
                       [-a IPADDR]

fcdpp-server.py

optional arguments:
  -h, --help            show this help message and exit
  -s, --swapiq          Swap the I and Q inputs, reversing the spectrum
  -p, --predsp          Offload some processing to an instance of predsp.py
  -l, --lna_gain        Enable the LNA gain.
  -m, --mixer_gain      Enable the mixer gain.
  -i IF_GAIN, --if_gain IF_GAIN
                        Specify the IF gain in dB as integer, default 0.
  -o PPM_OFFSET, --ppm_offset PPM_OFFSET
                        Frequency offset in parts per million, as float i.e.
                        3.9
  -a IPADDR, --ipaddr IPADDR
                        The server's IPv4 address to bind to. Default is all
                        addresses, i.e. 0.0.0.0 (alias addresses
                        can be used)

Predsp:
If you want to run fcdpp-server.py on embedded hardware (like BeagleBone Black in my case),
you probably would want to move all data preprocessing (eg. conversion from ints to floats)
to host running dspserver. For that purpouse I wrote small script called predsp.py. Usage:
 - on embedded host run 'fcdpp-server.py -p'
 - on more capable host run 'predsp.py' and 'dspserver --server <embedded host ip>'
 - run QtRadio or another client and point it to dspserver's address


#!/usr/bin/env python

# Copyright 2011 Ian Goldberg
#
# This file is part of Sphinx.
#
# Sphinx is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
#
# Sphinx is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with Sphinx.  If not, see
# <http://www.gnu.org/licenses/>.
#

"""
This module is used to parameterize the crypto primitives
used to encrypt/decrypt sphinx mixnet packets.
"""

import os
import binascii
from functools import reduce

from Crypto.Cipher import AES
from Crypto.Hash import SHA256, HMAC
from Crypto.Util import number
from Crypto.Util.strxor import strxor
from nacl.bindings import crypto_scalarmult
from pyblake2 import blake2b
from Cryptodome.Cipher import ChaCha20

from pylioness import Chacha20_Blake2b_Lioness, AES_SHA256_Lioness

from sphinxmixcrypto.nym_server import Nymserver
from sphinxmixcrypto.node import KeyMismatchError, BlockSizeMismatchError


BLINDING_HASH_PREFIX = b'\0x11'
RHO_HASH_PREFIX = b'\0x22'
MU_HASH_PREFIX = b'\0x33'
PI_HASH_PREFIX = b'\0x44'
TAU_HASH_PREFIX = b'\0x55'


class GroupP:
    "Group operations mod p"

    def __init__(self):
        # A 2048-bit prime
        self.__p = 1913410438251547134012138308293430882878846516487692248301804666518956860838 + \
        533652138552845585287022672941951578244576994631152454340178067976378738872954718198973 + \
        706028940706247921401744642825115746994081956867321580573181552152352900883786890992958 + \
        562877467321623953640627020158543955913969169796635999051041203446136976835775661506057 + \
        517706067943361819659545828482653492891104587913554024076544568803664876176841762410041 + \
        643804280840775935598361131923601799147307296410539233589716020166265519420170231237267 + \
        848121356044355838177752128425942891191400809793668864920967000989279066999182347251553 + \
        7714171774700422727

        # A 256-bit prime.  q | p-1, and (p-1)/(2q) is also prime
        self.__q = 106732665057690615308701680462846682779480968671143352109289849544853387479559

        # A generator of the 256-bit subgroup of order q
        self.generator = 484139441786349441222753937359181507222186847483440700310896462165694808760753 + \
                 313201440620938426400186061400541347047499861859506375079830182634177422300847 + \
                 601840574360281485737847061474817405657249365598958655758739651134727647466577 + \
                 884569940693579983363636508320621833059331551372071146035325524395420417805763 + \
                 312260922194735482986906987547422160345740734733202920357368017078519121268583 + \
                 377382750037104414214664818336930092771460011453820969206987379419171538261727 + \
                 876814959465431589529648553329257486681938507314187048365957770789256545184218 + \
                 1763727355979252885729688362656338077037492411991956527093735651034592

    def gensecret(self):
        return number.bytes_to_long(os.urandom(256)) % self.__q

    def expon(self, base, exp):
        return pow(base, exp, self.__p)

    def multiexpon(self, base, exps):
        return pow(base, reduce(lambda x, y: x*y % self.__q, exps), self.__p)

    def makeexp(self, data):
        return number.bytes_to_long(data) % self.__q

    def in_group(self, alpha):
        return alpha > 1 and alpha < (self.__p - 1) and \
            pow(alpha, self.__q, self.__p) == 1


class GroupECC:
    "Group operations in curve25519"
    size = 32

    def __init__(self):

        self.generator = self.basepoint()

    def basepoint(self):
        curve_bytes = b''
        curve_bytes += b'\x09'
        for i in range(1, 32):
            curve_bytes += b'\x00'
        return curve_bytes

    def makesecret(self, exp):
        """
        makesecret takes a byte string and converts them to a list of one byte integers
        before doing some bit manipulations and then returns the list of one byte ints
        """
        curve_out = []
        for c in exp:
            if isinstance(c, int):
                curve_out.append(c)
            else:
                curve_out.append(ord(c))
        curve_out[0] &= 248
        curve_out[31] &= 127
        curve_out[31] |= 64
        return bytes(bytearray(curve_out))

    def gensecret(self):
        return self.makesecret(os.urandom(self.size))

    def expon(self, base, exp):
        return crypto_scalarmult(bytes(exp), bytes(base))

    def multiexpon(self, base, exps):
        baseandexps = [base]
        baseandexps.extend(exps)
        return reduce(self.expon, baseandexps)

    def makeexp(self, data):
        assert len(data) == self.size
        return self.makesecret(data)

    def in_group(self, alpha):
        # All strings of length 32 are in the group, says DJB
        return len(alpha) == self.size


def SHA256_hash(data):
    h = SHA256.new()
    h.update(data)
    return h.digest()

def SHA256_hash_mac(key, data, digest_size=16):
    m = HMAC.new(key, msg=data, digestmod=SHA256)
    return m.digest()[:digest_size]

def Blake2_hash(data):
    b = blake2b(data=bytes(data))
    h = b.digest()
    return h[:32]

def Blake2_hash_mac(key, data, digest_size=16):
    b = blake2b(data=data, key=key, digest_size=digest_size)
    return b.digest()

def AES_stream_cipher(key):
    class xcounter:
        def __init__(self, size):
            self.i = 0
            self.size = size
        def __call__(self):
            if self.i > 2**self.size:
                raise Exception("AES_stream_cipher counter exhausted.")
            ii = number.long_to_bytes(self.i)
            ii = b'\x00' * (self.size-len(ii)) + ii
            self.i += 1
            return ii
    return AES.new(key, AES.MODE_CTR, counter=xcounter(16))

def Chacha20_stream_cipher(key):
    b = blake2b(data=key)
    new_key = b.digest()
    return ChaCha20.new(key=new_key[8:40], nonce=new_key[0:8])

class AES_Lioness:
    def __init__(self, key, block_size):
        self.cipher = AES_SHA256_Lioness(key, block_size)

    def encrypt(self, block):
        return self.cipher.encrypt(block)

    def decrypt(self, block):
        return self.cipher.decrypt(block)


class Chacha_Lioness:
    def __init__(self, key, block_size):
        c = Chacha20_stream_cipher(key)
        lioness_key = c.encrypt(b'\x00' * 208)
        self.cipher = Chacha20_Blake2b_Lioness(lioness_key, block_size)

    def encrypt(self, block):
        return self.cipher.encrypt(block)

    def decrypt(self, block):
        return self.cipher.decrypt(block)


class SphinxParams:
    k = 16 # in bytes, == 128 bits
    m = 1024 # size of message body, in bytes
    clients = {} # mapping of destinations to clients

    def __init__(self, r=5, group_class=None, lioness_class=None,
                 hash_func=None, hash_mac_func=None, stream_cipher=None):
        self.r = r
        assert group_class is not None
        self.group = group_class()
        self.lioness_class = lioness_class
        self.hash_func = hash_func
        self.hash_mac_func = hash_mac_func
        self.stream_cipher = stream_cipher
        self.nymserver = Nymserver(self)

    def get_dimensions(self):
        """
        header overhead = p + (2r + 2)s
        where p is the asymmetric element,
        s is the symmetric element and
        r is the max route length
        alpha 32 beta 176 gamma 16 delta 1024
        """
        alpha = self.group.size
        beta = (2 * self.r + 1) * self.k
        gamma = self.k
        delta = self.m
        return alpha, beta, gamma, delta

    def lioness_encrypt(self, key, data):
        c = self.lioness_class(key, len(data))
        return c.encrypt(data)

    def lioness_decrypt(self, key, data):
        c = self.lioness_class(key, len(data))
        return c.decrypt(data)

    def xor(self, str1, str2):
        # XOR two strings
        assert len(str1) == len(str2)
        return bytes(strxor(str1, str2))

    # The PRG; key is of length k, output is of length (2r+3)k
    def rho(self, key):
        assert len(key) == self.k
        c = self.stream_cipher(key)
        return c.encrypt(b"\x00" * ((2 * self.r + 3) * self.k))

    # The HMAC; key is of length k, output is of length k
    def mu(self, key, data):
        m = self.hash_mac_func(key, data)
        return m

    # The PRP; key is of length k, data is of length m
    def pi(self, key, data):
        assert len(key) == self.k
        assert len(data) == self.m
        return self.lioness_encrypt(key, data)

    # The inverse PRP; key is of length k, data is of length m
    def pii(self, key, data):
        if len(key) != self.k:
            raise KeyMismatchError()
        if len(data) != self.m:
            raise BlockSizeMismatchError()

        return self.lioness_decrypt(key, data)

    def hb(self, alpha, s):
        "Compute a hash of alpha and s to use as a blinding factor"
        return self.group.makeexp(self.hash_func(BLINDING_HASH_PREFIX + alpha + s))

    def hrho(self, s):
        "Compute a hash of s to use as a key for the PRG rho"
        return (self.hash_func(RHO_HASH_PREFIX + s))[:self.k]

    def hmu(self, s):
        "Compute a hash of s to use as a key for the HMAC mu"
        return (self.hash_func(MU_HASH_PREFIX + s))[:self.k]

    def hpi(self, s):
        "Compute a hash of s to use as a key for the PRP pi"
        return self.hash_func(PI_HASH_PREFIX + s)[:self.k]

    def htau(self, s):
        "Compute a hash of s to use to see if we've seen s before"
        return self.hash_func(TAU_HASH_PREFIX + s)

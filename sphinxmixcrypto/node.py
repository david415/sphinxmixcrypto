#!/usr/bin/env python

# Copyright 2011 Ian Goldberg
# Copyright 2016-2017 David Stainton
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

"""
This module includes cryptographic unwrapping of messages for mix net nodes
"""

import binascii
import zope.interface
import attr

from sphinxmixcrypto.padding import remove_padding
from sphinxmixcrypto.common import IPacketReplayCache, IMixPrivateKey
from sphinxmixcrypto.crypto_primitives import SECURITY_PARAMETER, GroupCurve25519, SphinxDigest
from sphinxmixcrypto.crypto_primitives import SphinxStreamCipher, SphinxLioness, xor, CURVE25519_SIZE
from sphinxmixcrypto.errors import HeaderAlphaGroupMismatchError, ReplayError, IncorrectMACError
from sphinxmixcrypto.errors import InvalidProcessDestinationError, InvalidMessageTypeError, NoSURBSAvailableError
from sphinxmixcrypto.errors import KeyMismatchError, SphinxBodySizeMismatchError


@attr.s(frozen=True)
class SphinxParams(object):

    max_hops = attr.ib(validator=attr.validators.instance_of(int))
    payload_size = attr.ib(validator=attr.validators.instance_of(int))

    def get_beta_cipher_size(self):
        """
        i am a helper method that is used to compute the size of the
        stream cipher output used in sphinx packet operations
        """
        return CURVE25519_SIZE + (2 * self.max_hops + 1) * SECURITY_PARAMETER

    def get_dimensions(self):
        """
        i am a helper method that returns the sphinx packet element sizes, a 4-tuple.
        e.g. payload = 1024 && 5 hops ==
        alpha 32 beta 176 gamma 16 delta 1024
        """
        alpha = CURVE25519_SIZE
        beta = (2 * self.max_hops + 1) * SECURITY_PARAMETER
        gamma = SECURITY_PARAMETER
        delta = self.payload_size
        return alpha, beta, gamma, delta


@attr.s(frozen=True)
class SphinxPacket(object):
    """
    I am a decoded sphinx packet
    """
    alpha = attr.ib(validator=attr.validators.instance_of(bytes))
    beta = attr.ib(validator=attr.validators.instance_of(bytes))
    gamma = attr.ib(validator=attr.validators.instance_of(bytes))
    delta = attr.ib(validator=attr.validators.instance_of(bytes))


DSPEC = b"\x00"  # The special destination


# Decode the prefix-free encoding.
# Returns the type, value, and the remainder of the input string
def prefix_free_decode(s):
    if len(s) == 0:
        return None, None, None
    if isinstance(s[0], int):
        l = s[0]
    else:
        l = ord(s[0])
    if l == 0:
        return 'process', None, s[1:]
    if l == 255:
        return 'mix', s[:SECURITY_PARAMETER], s[SECURITY_PARAMETER:]
    if l < 128:
        return 'client', s[1:l + 1], s[l + 1:]
    return None, None, None


def destination_encode(dest):
    """
    encode destination
    """
    assert len(dest) >= 1 and len(dest) <= 127
    return b"%c" % len(dest) + dest


class UnwrappedMessage:
    def __init__(self):
        self.tuple_next_hop = ()
        self.tuple_exit_hop = ()
        self.tuple_client_hop = ()


@zope.interface.implementer(IPacketReplayCache)
class PacketReplayCacheDict:

    def __init__(self):
        self.cache = {}

    def has_seen(self, tag):
        return tag in self.cache

    def set_seen(self, tag):
        self.cache[tag] = True

    def flush(self):
        self.cache = {}


def sphinx_packet_unwrap(params, replay_cache, private_key, packet):
    """
    sphinx_packet_unwrap returns a UnwrappedMessage given the replay
    cache, private key and a packet or raises an exception if an error
    was encountered
    """
    assert IPacketReplayCache.providedBy(replay_cache)
    assert IMixPrivateKey.providedBy(private_key)

    if len(packet.delta) != params.payload_size:
        raise SphinxBodySizeMismatchError()
    result = UnwrappedMessage()
    group = GroupCurve25519()
    digest = SphinxDigest()
    stream_cipher = SphinxStreamCipher()
    block_cipher = SphinxLioness()
    if not group.in_group(packet.alpha):
        raise HeaderAlphaGroupMismatchError()
    s = group.expon(packet.alpha, private_key.get_private_key())
    tag = digest.hash_replay(s)
    if replay_cache.has_seen(tag):
        raise ReplayError()
    if packet.gamma != digest.hmac(digest.create_hmac_key(s), packet.beta):
        raise IncorrectMACError()
    replay_cache.set_seen(tag)
    payload = block_cipher.decrypt(block_cipher.create_block_cipher_key(s), packet.delta)
    B = xor(packet.beta + (b"\x00" * (2 * SECURITY_PARAMETER)), stream_cipher.generate_stream(digest.create_stream_cipher_key(s), params.get_beta_cipher_size()))
    message_type, val, rest = prefix_free_decode(B)

    if message_type == "mix":
        b = digest.hash_blinding(packet.alpha, s)
        alpha = group.expon(packet.alpha, b)
        gamma = B[SECURITY_PARAMETER:SECURITY_PARAMETER * 2]
        beta = B[SECURITY_PARAMETER * 2:]
        result.tuple_next_hop = (val, (alpha, beta, gamma), payload)
        return result
    elif message_type == "process":
        if payload[:SECURITY_PARAMETER] == (b"\x00" * SECURITY_PARAMETER):
            inner_type, val, rest = prefix_free_decode(payload[SECURITY_PARAMETER:])
            if inner_type == "client":
                # We're to deliver rest (unpadded) to val
                body = remove_padding(rest)
                result.tuple_exit_hop = (val, body)
                return result
        raise InvalidProcessDestinationError()
    elif message_type == "client":
        id = rest[:SECURITY_PARAMETER]
        result.tuple_client_hop = (val, id, payload)
        return result
    raise InvalidMessageTypeError()


import py.test
import binascii

from sphinxmixcrypto.params import SphinxParams, GroupECC, Chacha_Lioness, Chacha20_stream_cipher, Blake2_hash, Blake2_hash_mac
from sphinxmixcrypto import SphinxNode
from sphinxmixcrypto.node import ReplayError, BlockSizeMismatchError, SphinxNodeState
from sphinxmixcrypto.client import SphinxClient, rand_subset, create_forward_message
from sphinxmixcrypto.common import RandReader


class FixedNoiseReader():

    def __init__(self, hexed_noise):
        self.noise = binascii.unhexlify(hexed_noise)
        self.count = 0
        self.fallback = RandReader()

    def read(self, n):
        if n > len(self.noise):
            print("%s > %s" % (n, len(self.noise)))
            return self.fallback.read(n)
        ret = self.noise[:n]
        self.noise = self.noise[n:]
        self.count += n
        return ret


class TestSphinxCorrectness():

    def newTestRoute(self, numHops):
        self.r = numHops
        self.params = SphinxParams(
            self.r, group_class=GroupECC,
            hash_func=Blake2_hash,
            hash_mac_func=Blake2_hash_mac,
            lioness_class=Chacha_Lioness,
            stream_cipher=Chacha20_stream_cipher,
        )
        self.node_map = {}
        self.consensus = {}
        rand_reader = RandReader()
        for i in range(numHops):
            node = SphinxNode(self.params, rand_reader=rand_reader)
            self.node_map[node.get_id()] = node
            self.consensus[node.get_id()] = node.public_key
        route = rand_subset(self.node_map.keys(), self.r)
        return route

    def test_sphinx_single_hop(self):
        route = self.newTestRoute(1)
        destination = b"dest"
        message = b"this is a test"
        rand_reader = RandReader()
        alpha, beta, gamma, delta = create_forward_message(self.params, route, self.consensus, destination, message, rand_reader)
        header = alpha, beta, gamma
        payload = delta
        result = self.node_map[route[0]].unwrap(header, payload)
        assert len(result.tuple_exit_hop) == 2
        assert len(result.tuple_next_hop) == 0
        assert len(result.tuple_client_hop) == 0
        received_dest, received_message = result.tuple_exit_hop
        assert received_dest == destination
        assert received_message == message

    def test_sphinx_replay(self):
        route = self.newTestRoute(5)
        destination = b"dest"
        message = b"this is a test"
        rand_reader = RandReader()
        alpha, beta, gamma, delta = create_forward_message(self.params, route, self.consensus, destination, message, rand_reader)
        header = alpha, beta, gamma
        payload = delta
        self.node_map[route[0]].unwrap(header, payload)
        py.test.raises(ReplayError, self.node_map[route[0]].unwrap, header, payload)

    def test_sphinx_assoc_data(self):
        route = self.newTestRoute(5)
        destination = b"dest"
        message = b"this is a test"
        rand_reader = RandReader()
        alpha, beta, gamma, delta = create_forward_message(self.params, route, self.consensus, destination, message, rand_reader)
        header = alpha, beta, gamma
        payload = delta
        assert payload is not None
        py.test.raises(BlockSizeMismatchError, self.node_map[route[0]].unwrap, header, b"somethingelse!!!!!!!!!!!!!!")


class TestSphinxEnd2End():

    def setUpMixVectors(self, rand_reader, client_id=None):
        hexedState = [
            {
                "id": binascii.unhexlify("ff2182654d0000000000000000000000"),
                "public_key": binascii.unhexlify("d7314c8d2ba771dbe2982fa6299844f1b92736881e78ae7644f4bccbf8817a69"),
                "private_key": binascii.unhexlify("306e5a009897d4e134727037f9b275294bd01fb33c0c7dbe5f1fdaed765d0c47"),
            },
            {
                "id": binascii.unhexlify("ff0f9a62780000000000000000000000"),
                "public_key": binascii.unhexlify("5ce56657b8af66bd47df2469b10065206a2fd777a0cd17b104160256810bc976"),
                "private_key": binascii.unhexlify("98967364dfe5d5f5d0180c727797d9111f3b1da573c25036ba16396579c25048"),
            },
            {
                "id": binascii.unhexlify("ffc74d10550000000000000000000000"),
                "public_key": binascii.unhexlify("47ade5905376604cde0b57e732936b4298281c8a67b6a62c6107482eb69e2941"),
                "private_key": binascii.unhexlify("18c539194baae419f50ff117cbf15456a0762845af3d0a77ba85024ba488ce58"),
            },
            {
                "id": binascii.unhexlify("ffbb0407380000000000000000000000"),
                "public_key": binascii.unhexlify("4704aff4bc2aaaa3fd187d52913a203aba4e19f6e7b491bda8c8e67daa8daa67"),
                "private_key": binascii.unhexlify("781e6fc7636d70dae8ebf2337538b22d7b64281a55505c1f12921e7b61f09c59"),
            },
            {
                "id": binascii.unhexlify("ff81855a360000000000000000000000"),
                "public_key": binascii.unhexlify("73514173ee741afacdd4733e84f629b5cb9e34d28d072d749a8171fc6d64a930"),
                "private_key": binascii.unhexlify("9863a8f1b5307938cd4bc9782411e9eea0a38b9144d096bd923085dfb8534277"),
            },

        ]
        self.r = 5
        self.params = SphinxParams(
            self.r, group_class=GroupECC,
            hash_func=Blake2_hash,
            hash_mac_func=Blake2_hash_mac,
            lioness_class=Chacha_Lioness,
            stream_cipher=Chacha20_stream_cipher,
        )

        self.node_map = {}
        self.consensus = {}
        self.route = []

        # Create some nodes
        for i in range(len(hexedState)):
            state = SphinxNodeState()
            state.id = hexedState[i]['id']
            state.public_key = hexedState[i]['public_key']
            state.private_key = hexedState[i]['private_key']
            node = SphinxNode(self.params, state=state)
            self.route.append(node.id)
            self.node_map[node.get_id()] = node
            self.consensus[node.get_id()] = node.public_key

        # Create a client
        self.alice_client = SphinxClient(self.params,
                                         id=client_id,
                                         rand_reader=rand_reader)

    def test_client_surb(self):
        rand_reader = FixedNoiseReader("b5451d2eb2faf3f84bc4778ace6516e73e9da6c597e6f96f7e63c7ca6c9456018be9fd84883e4469a736c66fcaeceacf080fb06bc45859796707548c356c462594d1418b5349daf8fffe21a67affec10c0a2e3639c5bd9e8a9ddde5caf2e1db802995f54beae23305f2241c6517d301808c0946d5895bfd0d4b53d8ab2760e4ec8d4b2309eec239eedbab2c6ae532da37f3b633e256c6b551ed76321cc1f301d74a0a8a0673ea7e489e984543ca05fe0ff373a6f3ed4eeeaafd18292e3b182c25216aeb8")

        self.setUpMixVectors(rand_reader)
        nym_id = b"Cypherpunk"
        nym_tuple = self.alice_client.create_nym(self.route, self.consensus)
        self.params.nymserver.add_surb(nym_id, nym_tuple)
        message = b"Open, secure and reliable connectivity is necessary (although not sufficient) to excercise the human rights such as freedom of expression and freedom of association [FOC], as defined in the Universal Declaration of Human Rights [UDHR]."

        nym_result = self.params.nymserver.process(nym_id, message)
        self.alpha = binascii.unhexlify("cbe28bea4d68103461bc0cc2db4b6c4f38bc82af83f5f1de998c33d46c15f72d")
        self.beta = binascii.unhexlify("a5578dc72fcea3501169472b0877ca46627789750820b29a3298151e12e04781645f6007b6e773e4b7177a67adf30d0ec02c472ddf7609eba1a1130c80789832fb201eed849c02244465f39a70d7520d641be371020083946832d2f7da386d93b4627b0121502e5812209d674b3a108016618b2e9f210978f46faaa2a7e97a4d678a106631581cc51120946f5915ee2bfd9db11e5ec93ae7ffe4d4dc8ab66985cfe9da441b708e4e5dc7c00ea42abf1a")
        self.gamma = binascii.unhexlify("49533c3dda5a7cc2fa611e3616a70ce4")
        self.delta = binascii.unhexlify("0a9411a57044d20b6c4004c730a78d79550dc2f22ba1c9c05e1d15e0fcadb6b1b353f028109fd193cb7c14af3251e6940572c7cd4243977896504ce0b59b17e8da04de5eb046a92f1877b55d43def3cc11a69a11050a8abdceb45bc1f09a22960fdffce720e5ed5767fbb62be1fd369dcdea861fd8582d01666a08bf3c8fb691ac5d2afca82f4759029f8425374ae4a4c91d44d05cb1a64193319d9413de7d2cfdffe253888535a8493ab8a0949a870ae512d2137630e2e4b2d772f6ee9d3b9d8cadd2f6dc34922701b21fa69f1be6d0367a26c2875cb7afffe60d59597cc084854beebd80d559cf14fcb6642c4ab9102b2da409685f5ca9a23b6c718362ccd6405d993dbd9471b4e7564631ce714d9c022852113268481930658e5cee6d2538feb9521164b2b1d4d68c76967e2a8e362ef8f497d521ee0d57bcd7c8fcc4c673f8f8d700c9c71f70c73194f2eddf03f954066372918693f8e12fc980e1b8ad765c8806c0ba144b86277170b12df16b47de5a2596b2149c4408afbe8f790d3cebf1715d1c4a9ed5157b130a66a73001f6f344c74438965e85d3cac84932082e6b17140f6eb901e3de7b3a16a76bdde2972c557d573830e8a455973de43201b562f63f5b3dca8555b5215fa138e81da900358ddb4d123b57b4a4cac0bfebc6ae3c7d54820ca1f3ee9908f7cb81200afeb1fdafdfbbc08b15d8271fd18cfd7344b36bdd16cca082235c3790888dae22e547bf436982c1a1935e2627f1bb16a3b4942f474d2ec1ff15eb6c3c4e320892ca1615ecd462007e51fbc69817719e6d641c101aa153bff207974bbb4f9553a8d6fb0cfa2cb1a497f9eee32f7c084e97256c72f06f020f33a0c079f3f69c2ce0e2826cc396587d80c9485e26f70633b70ad2e2d531a44407d101628c0bdae0cd47d6032e97b73e1231c3db06a2ead13eb20878fc198a345dd9dafc54b0cc56bcf9aa64e85002ff91a3f01dc97de5e85d68707a4909385cefbd6263cf9624a64d9052291da48d33ac401854cce4d6a7d21be4b5f1f4616e1784226603fdadd45d802ab226c81ec1fc1827310c2c99ce1c7ee28f38fbc7cf637132a1a2b1e5835762b41f0c7180a7738bac5cedebc11cdbf229e2155a085349b93cb94ce4285ea739673cc719e46cacb56663564057df1a0a2f688ed216336ff695337d6922f0185c23c3c04294388da192d9ae2b51ff18a8cc4d3212e1b2b19fed7b8f3662c2f9bd463f75e1e7c738db6b204f8f5aa8176e238d41c8d828b124e78c294be2d5b2bf0724958b787b0bea98d9a1534fc9975d66ee119b47b2e3017c9bba9431118c3611840b0ddcb00450024d484080d29c3896d92913eaca52d67f313a482fcc6ab616673926bdbdb1a2e62bcb055755ae5b3a975996e40736fde300717431c7d7b182369f90a092aef94e58e0ea5a4b15e76d")
        self.match_hop = "ff81855a360000000000000000000000"
        result = self.mixnet_test_state_machine(nym_result.message_result)
        received_client_message = result.tuple_message[1]
        assert message == received_client_message

    def mixnet_test_state_machine(self, result):
        i = 0
        while True:
            if result.tuple_next_hop:
                if result.tuple_next_hop[0] == binascii.unhexlify(self.match_hop):
                    # print "alpha %s" % binascii.hexlify(result.tuple_next_hop[1][0])
                    # print "beta %s" % binascii.hexlify(result.tuple_next_hop[1][1])
                    # print "gamma %s" % binascii.hexlify(result.tuple_next_hop[1][2])
                    # print "delta %s" % binascii.hexlify(result.tuple_next_hop[2])
                    assert result.tuple_next_hop[1][0] == self.alpha
                    assert result.tuple_next_hop[1][1] == self.beta
                    assert result.tuple_next_hop[1][2] == self.gamma
                    assert result.tuple_next_hop[2] == self.delta

                result = self.send_to_mix(result.tuple_next_hop[0], result.tuple_next_hop[1], result.tuple_next_hop[2])
                i += 1
            elif result.tuple_exit_hop:
                # print("Deliver [%s] to [%s]" % (result.tuple_exit_hop[1], binascii.hexlify(result.tuple_exit_hop[0])))
                break
            elif result.tuple_client_hop:
                result = self.send_to_client(*result.tuple_client_hop)
                # print("message received by [%s]" % result.tuple_message[0])
                return result

    def send_to_client(self, client_id, message_id, delta):
        # print("send_to_client client_id %s message_id %s delta len %s" % (client_id, binascii.hexlify(message_id), len(delta)))
        return self.params.clients[client_id].decrypt(message_id, delta)

    def send_to_mix(self, destination, header, payload):
        return self.node_map[destination].unwrap(header, payload)

    def test_end_to_end(self):
        rand_reader = FixedNoiseReader("82c8ad63392a5f59347b043e1244e68d52eb853921e2656f188d33e59a1410b43c78e065c89b26bc7b498dd6c0f24925c67a7ac0d4a191937bc7698f650391")
        self.setUpMixVectors(rand_reader, client_id=binascii.unhexlify("436c69656e74206564343564326264"))
        message = b"the quick brown fox"
        alpha, beta, gamma, delta = create_forward_message(self.params, self.route, self.consensus,
                                                           self.route[-1], message, rand_reader)
        header = alpha, beta, gamma

        # Send it to the first node for processing
        result = self.node_map[self.route[0]].unwrap(header, delta)
        self.alpha = binascii.unhexlify("b9bc2a81df782c98a8e2b8560dc50647e2f3c013ed563b021df3e0b45378d66c")
        self.beta = binascii.unhexlify("9f486475acc1bd3bc551700f58108ea4029a250b5e893eaaf8aeb0811d84094816b3904f69d45921448454de0eb18bfda49832492a127a5682231d3848a3cb06ca17c3427063f80d662997b30bc9307a676cd6972716d1d6ee59b657f368b0fdb0245872e5157dd3de788341518c328395b415b516bd47efb86302edf840eebd9de432e08d6b9fddd4d55f75112332e403d78e536193aa172c0dbffbc9631d8c877214abef61d54bd0a35114e5f0eace")
        self.gamma = binascii.unhexlify("0b05b2c7b3cdb8e5532d409be5f32a16")
        self.delta = binascii.unhexlify("320e9422cb6ecdc8de8cebacf32dd676d9e8142070856275ff39efacc39d09ff61f75f2633c232015f638d4ac72ee211b41d1f3351f600b47c1638640956fff1f00f61a744a4df75ed730de2eb3b5bb4fa65df8d775d606705ccf0ce8f66a444f04dfaee50c0d23c4ae1b217bf28e49db77df4b91aba049514ed1c8f55648f176b4a9d3045433d838063a830523e6e5bdc53e0278734436df2a3936df05b2ae68fadf26e7913216606ec1dbcd64cf54e0f63bd03e08bcd7d73eb6336d70104b1f85c0d8086a4da656d1bdc24b91cc443efa9022223af8d651d04b5611931cd7d91fe4a5ef031e0409ff80fc398e350fe9307d9b3c673b60c162c5581630ae7733f947a214979f7e7ef8e8481a1e59eec700d92e6d8ca279a06d4ff3c6f960c74b6473842c44323576b383de01a4b16077fe740d6f3dfabad6fc85d3b972dccca9eb9040f9b2df3b21e7e679df41d6a5750df3c9da5a9ca2a5d9a7b233378a195e7ec995fc588fef6f537ec082d7b755dffee56646bc75f7f38bdb91945e3aa6aeee0fe5cd31eed271e69b930a9893e3dc0ca8516afa382eb72fab61e915b8b70babef87a69460fec2e26a3c34983271766746f034c4562d62d494e70b444b6ff7d71f866133858fece4baaa18442a7528a0cba298169c3c315b00369569a23040d26db6df452a7d79f7ed2e7aebcdee23f34765f0f91917a00353c4692f64c20f4517cd7826f1962dd3fcda86a4ba0772fb5d9466ab340359233bf6452f4b5cd208f5a40114a1ceed1fb643a4e7bb676bcb16bd8eb78b0082a3a1dcc17f84f984c820885ac90cc9f249fec002d929747875f4fb31752d5d586addb512e122256e4c1350e7df34a2c1d708f4a4f51ce5527e2b9757a4cf199be26d53124fe0ac965694723224b9fbccf78ad3c2d873d480569b853ffdb526b9a5b9f17d26f27cad103237e19e69c24cc8d27637f1cbef38aa93eb5d221878d806373579e1760facd50690926260a3ae0a544f5788ef11d03266295d6794b1ba3d5861aa715b1e989f09fe3ed645ba6a5ccb9b4474d874189f149d9617bc0cf3f071aaa04d3f2d7a5d8b143b234f266dfcbd892ba502215785c39abf98b5617c4b2a4c9284d562f8c26da44200fbd526a4469677cb925a6a26322ac2e651df6f32b3fe0fc393a6eab18a48b7d2c54346ae5cc0ffcb539adf0ce398d180f78577427749a8c99edf55f91677fcc451762978b384966baeb63b20d4ad7e5ec2f9bc63812ffb8a14074cbca66bd80b3df6cb50024f332f4c466efb5bed156845d3deb6785df4d1dc99021ce70a1cd575b7e65739ee7e02baf955605ee3cc9e335e811bd28eda3482fa8cd25e50e56950828bc0bfe3d0489b0149242c4e5d39d7d4f8f1b049c530e8e827359573bcc18abcc30ee639341375b56cb6ffc5702e0912955059ee974bc603f")
        self.match_hop = "ff81855a360000000000000000000000"
        self.mixnet_test_state_machine(result)
        assert self.node_map[self.route[-1]].received[0] == message
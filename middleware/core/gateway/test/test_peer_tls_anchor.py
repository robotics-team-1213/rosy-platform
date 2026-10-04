import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from core_api_web.api.peer_pairing.tls_anchor import configured_tls_anchor


class TLSAnchor(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.now=datetime.now(timezone.utc)
        self.ca_key=ec.generate_private_key(ec.SECP256R1())
        self.leaf_key=ec.generate_private_key(ec.SECP256R1())
        self.name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Fixture Receiver CA')])
        self.ca=self.certificate(True)
        self.leaf=self.certificate(False)
        self.config={'network':{'tls':{}}}
        self.write()

    def certificate(self, ca, hostname='fixture.local', expired=False):
        public=self.ca_key.public_key() if ca else self.leaf_key.public_key()
        start=self.now-timedelta(days=2)
        end=self.now-timedelta(days=1) if expired else self.now+timedelta(days=30)
        subject=self.name if ca else x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,hostname)])
        builder=(x509.CertificateBuilder().subject_name(subject).issuer_name(self.name)
                 .public_key(public).serial_number(x509.random_serial_number())
                 .not_valid_before(start).not_valid_after(end)
                 .add_extension(x509.BasicConstraints(ca, 0 if ca else None), critical=True)
                 .add_extension(x509.KeyUsage(True,False,False,False,False,ca,ca,None,None),critical=True)
                 .add_extension(x509.SubjectKeyIdentifier.from_public_key(public),critical=False)
                 .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.ca_key.public_key()),critical=False))
        if not ca:
            builder=builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]),critical=False)
            builder=builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
        return builder.sign(self.ca_key,hashes.SHA256())

    def write(self):
        for name,cert in [('ca_file',self.ca),('cert_file',self.leaf)]:
            path=self.folder/(name+'.pem');path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            self.config['network']['tls'][name]=str(path)
        key=self.folder/'key.pem'
        key.write_bytes(self.leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        self.config['network']['tls']['key_file']=str(key)

    def test_actual_ca_chain_hostname_and_public_fingerprint(self):
        with patch('socket.gethostname',return_value='fixture'):
            value=configured_tls_anchor(self.config)
        self.assertEqual('fixture.local',value['tls_hostname'])
        self.assertEqual(self.ca.fingerprint(hashes.SHA256()).hex(),value['tls_ca_sha256'])
        self.assertEqual(self.ca.public_bytes(serialization.Encoding.PEM).decode(),value['tls_ca_pem'])
        self.assertNotIn('PRIVATE',value['tls_ca_pem'])

    def test_wrong_ca_hostname_expiry_constraint_and_bounds_fail_closed(self):
        with patch('socket.gethostname',return_value='fixture'):
            for mutation in ('hostname','expired','not-ca','foreign-ca','oversized'):
                with self.subTest(mutation=mutation):
                    self.ca=self.certificate(True);self.leaf=self.certificate(False);self.write()
                    if mutation=='hostname': self.leaf=self.certificate(False,'foreign.local');self.write()
                    elif mutation=='expired': self.leaf=self.certificate(False,expired=True);self.write()
                    elif mutation=='not-ca': self.ca=self.leaf;self.write()
                    elif mutation=='foreign-ca': self.ca_key=ec.generate_private_key(ec.SECP256R1());self.ca=self.certificate(True);self.write()
                    else: Path(self.config['network']['tls']['ca_file']).write_bytes(b'x'*8193)
                    with self.assertRaises(ValueError): configured_tls_anchor(self.config)

    def test_tls_guard_optional_ca_does_not_allow_unknown_or_partial_config(self):
        module_path=Path(__file__).resolve().parents[1] / 'core/api_tls.py'
        spec=importlib.util.spec_from_file_location('candidate_tls_guard',module_path)
        guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
        with patch('socket.gethostname',return_value='fixture'):
            self.assertEqual(self.config['network']['tls']['cert_file'],guard.server_tls_options(self.config)['ssl_certfile'])
            self.config['network']['tls']['anything']='unexpected'
            with self.assertRaises(ValueError): guard.server_tls_options(self.config)
            del self.config['network']['tls']['anything']
            del self.config['network']['tls']['key_file']
            with self.assertRaises(ValueError): guard.server_tls_options(self.config)
        self.assertEqual({},configured_tls_anchor({'network':{'tls':{'cert_file':'existing-public-cert','key_file':'existing-public-key'}}}))

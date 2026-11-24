from abc import abstractmethod
from utf.interfaces import ControlInterface
from utf.utils.logger import Loggable
from typing import Optional
from ssl import *
import ssl
from socket import *
import datetime
import sys
import threading
import logging


def create_interface(config) -> ControlInterface:
    return TLSServerInterface(config)



class TLSServerInterface(ControlInterface, Loggable):
    def __init__(self, config: dict):
        super().__init__(config)
        self.config = config
        
        
    def start_server(self, type = 0):
        self.BYTES_TO_RECEIVE = 256  # Change this to BYTES_TO_RECEIVE present in app.c
        self.MAX_DATA_BYTES = self.BYTES_TO_RECEIVE * 1024 * 1024
        self.TIMEOUT = 30
        self.type = type
        self.stop_thread = False
        self.connection = None
        self.client_address = None
        
        self.message = 'start12345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456712345678901234563747er737487er871234567890123456789012345678901234567890123456789012345678901234567890endend'
        self.data_out = self.message.encode()
    
        self.server_socket = socket(AF_INET, SOCK_STREAM)
        self.server_socket.bind(('0.0.0.0', 443))
        self.server_socket.listen(10)
        self.server_socket.settimeout(2)
        
        # Choose the appropriate protocol based on the Python version
        if sys.version_info < (3, 0):
            self.ssl_context = SSLContext(PROTOCOL_TLSv1)
        else:
            self.ssl_context = SSLContext(PROTOCOL_TLS_SERVER)
        
        self.ssl_context.verify_mode = ssl.CERT_NONE
        self.ssl_context.load_cert_chain(certfile='certificates/server-cert.pem', keyfile='certificates/server-key.pem')
        self.tls_server = self.ssl_context.wrap_socket(self.server_socket, server_side=True)
        
        self.logger.info(f"Server started")
        
        self.thread = threading.Thread(target=self.server_thread)
        self.thread.start()
        
    
    def server_thread(self):
        start_time = datetime.datetime.now()
        elapsed_time = 0
        self.logger.info(f'Waiting for connection')
        while True:
            try:
                self.connection, self.client_address = self.tls_server.accept()
            except:
                elapsed_time = (datetime.datetime.now() - start_time).total_seconds()
                if self.stop_thread == True or elapsed_time > self.TIMEOUT:
                    self.logger.info(f'Stopping server. No connection made')
                    self.server_socket.close()
                    return
                else:
                    continue;
            if self.connection:
                break;
        
        self.logger.info(f'connection from {self.client_address}')
        
        if self.type == 0:
            self.logger.info("starting TX")
            self.ssl_tx()
        else:
            self.logger.info("starting RX")
            self.ssl_rx()
        
        
        self.connection.close()
        self.server_socket.close()
        
    def stop(self):
        self.stop_thread = True
        self.thread.join()
        if self.connection:
            self.connection.close()
        self.server_socket.close()
        
        
    def ssl_tx(self):
        total_sent_bytes = 0
    
        while True:
            try:
                self.connection.send(self.data_out)
                total_sent_bytes += len(self.data_out)
            except OSError:
                self.logger.info("Connection closed by client.")
                break
    
            if total_sent_bytes >= self.MAX_DATA_BYTES:
                self.logger.info(f"Sent {MAX_DATA_BYTES} bytes of data. Exiting...")
                break
        
        self.logger.info(f"Sent {total_sent_bytes} bytes")

    def ssl_rx(self):
        data_count = 0
        start_time = datetime.datetime.now()
        self.connection.settimeout(2)

        while True:
            elapsed_time = (datetime.datetime.now() - start_time).total_seconds()
    
            if int(elapsed_time) > self.TIMEOUT or self.stop_thread == True:
                self.logger.info("Timeout.")
                break
    
            try:
                data_in = self.connection.recv(1370)
    
                if not data_in:
                    self.logger.info("Connection closed by client.")
                    break
    
                data_count += len(data_in)
    
                if data_count >= self.MAX_DATA_BYTES:
                    self.logger.info("Received {}MB data. Exiting...".format(BYTES_TO_SEND))
                    break
            except (OSError, IOError):
                self.logger.info("Connection closed by client.")
                break
    
        elapsed_time = (datetime.datetime.now() - start_time).total_seconds()
        throughput = float(data_count * 8) / (1000 * 1000 * elapsed_time)
        throughput = round(throughput, 2)
        self.logger.info("data_count is {}".format(data_count))
        self.logger.info("throughput is {} in {} seconds".format(throughput, elapsed_time))

if __name__ == "__main__":
    server = TLSServerInterface(None)
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    server.start_server(1)

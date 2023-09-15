Requied Paths available in container
- /secrets/nginx-cert.pem
- /secrets/nginx-key.pem



## Generating TLS certs for nginx

openssl req -x509 -batch -newkey rsa:2048 \
    -keyout /opt/object_database/secrets/nginx-key.pem \
    -nodes \
    -out /opt/object_database/secrets/nginx-cert.pem \
    -sha256 \
    -days 1000 \
    -subj '/C=US/ST=New York/L=New York/CN=localhost'

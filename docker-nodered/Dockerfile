FROM nodered/node-red:latest
WORKDIR /data
COPY ./data/package.json /data
RUN npm install --unsafe-perm --no-update-notifier --no-fund --only=production
WORKDIR /usr/src/node-red

COPY ./data/settings.js /data/settings.js
COPY ./data/flows_cred.json /data/flows_cred.json
COPY ./data/flows.json /data/flows.json

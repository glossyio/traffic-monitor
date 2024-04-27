FROM nodered/node-red:latest
WORKDIR /data
COPY ~/code/nodered/data/package.json /data
RUN npm install --unsafe-perm --no-update-notifier --no-fund --only=production
WORKDIR /usr/src/node-red

COPY ~/code/nodered/data/settings.js /data/settings.js
COPY ~/code/nodered/data/flows_cred.json /data/flows_cred.json
COPY ~/code/nodered/data/flows.json /data/flows.json

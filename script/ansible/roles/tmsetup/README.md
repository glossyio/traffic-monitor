tmsetup
=========

Local role for installation of Traffic Monitor software stack on Raspbery Pi device

Requirements
------------

Tested on versions.  May work on lower versions but this is earliest tested.

- ansble_version: `>=2.17.8`
- python_version: `>=3.10.12`

- ansible_collections: `community.general`

Role Variables
--------------

- `tmsetup_codeowner`: STRING # The user that non-system services will run under and all data will be owned by
  - default: `'{{ ansible_user_id }}'`
- `tmsetup_codehomedir`: STRING # Path to directory for frigate and other application data will be stored
  - default: `'{{ ansible_user_dir }}/code'`
- `tmsetup_nodereddir`: STRING # Path to directory for nodered installation
  - default: `'{{ ansible_user_dir }}/.node-red'`
- `tmsetup_timezone`: STRING - Timezone to set system clock to. You can view a list of availbe timezones by running `timedatectl list-timezones`
  - default: `'America/Los_Angeles'`
- `tmsetup_frigate_rtsp_password`: STRING # Password for frigate rtsp for frigate container
  - default: `password`
- `tmsetup_frigate_mqtt_user`: STRING # MQTT user for Frigate container
  - default: `mqtt_user`
- `tmsetup_frigate_mqtt_password`:  STRING # MQTT user password for frigate container
  - default: `mqtt_pass`
- `tmsetup_frigate_tpu_device`:  STRING # Coral TPU Device.  Currently supported either 'pci' or 'usb'
  - default: `pci`

Example Playbook
----------------

```yml
---
- name: Traffic Monitr Setup
  hosts: localhost
  tasks:
    - name: Run tmsetup role
      ansible.builtin.import_role:
        name: tmsetup
...
```

"""Render tmsetup templates and check what the device gets. Off-device; no Ansible run needed."""

import ast
import re

import pytest
import yaml
from tmsetup_render import load_role_yaml, render

LOCATIONS = load_role_yaml("vars/main.yml")["tmsetup_revproxy_locations"]


def location(name):
    return render(f"container/revproxy/tm/locations/{name}.j2")


def test_data_export_downloads_are_proxied_to_node_red():
    """ui-database's download links are root-relative (/storefiles?files=...), so they need their own location (#211)."""
    assert "storefiles.conf" in LOCATIONS
    conf = location("storefiles.conf")
    assert "location /storefiles {" in conf
    assert "proxy_pass http://127.0.0.1:1880;" in conf
    assert "proxy_buffering off;" in conf
    assert "proxy_read_timeout 30m;" in conf


def published_ports(unit_text):
    return [line.split("=", 1)[1] for line in unit_text.splitlines() if line.startswith("PublishPort=")]


def test_pod_publishes_app_ports_on_loopback_only():
    pod = render("container/traffic-monitor.pod.j2", tmsetup_mqtt_lan_open=False)
    assert published_ports(pod) == [
        "127.0.0.1:1880:1880",
        "127.0.0.1:1883:1883",
        "127.0.0.1:5000:5000",
        "127.0.0.1:8971:8971",
    ]


def test_pod_opens_mqtt_to_the_network_only_with_a_broker_login():
    # Task 10 sets tmsetup_mqtt_lan_open when node-red-tm.env has a broker login
    pod = render("container/traffic-monitor.pod.j2", tmsetup_mqtt_lan_open=True)
    assert "1883:1883" in published_ports(pod)
    assert "127.0.0.1:1883:1883" not in published_ports(pod)


def revproxy_unit():
    return render(
        "container/revproxy/revproxy.container.j2",
        tmsetup_codedir="/opt/traffic-monitor",
        tmsetup_revproxy_config_mounts=load_role_yaml("vars/main.yml")["tmsetup_revproxy_config_mounts"],
    ).splitlines()


def test_revproxy_runs_on_the_host_network_outside_the_pod():
    unit = revproxy_unit()
    assert "Network=host" in unit
    assert not any(line.startswith("Pod=") for line in unit)


def test_revproxy_keeps_its_bind_mounted_config():
    unit = revproxy_unit()
    assert "Volume=/opt/traffic-monitor/revproxy/nginx.conf:/etc/nginx/nginx.conf:ro" in unit
    assert "Volume=/opt/traffic-monitor/revproxy/tm:/etc/nginx/tm:ro" in unit


def test_revproxy_keeps_retrying_while_port_80_is_still_taken():
    unit = revproxy_unit()
    assert "StartLimitIntervalSec=0" in unit
    assert "RestartSec=5" in unit


@pytest.mark.parametrize("name", LOCATIONS)
def test_no_location_goes_through_host_containers_internal(name):
    assert "host.containers.internal" not in location(name)


def test_host_apps_are_proxied_on_loopback():
    assert "proxy_pass http://127.0.0.1:1984/;" in location("go2rtc.conf")
    assert "proxy_pass http://127.0.0.1:9090;" in location("cockpit.conf")


def test_feeds_accepts_only_get_and_plain_stream_names():
    conf = location("go2rtc.conf")
    assert "limit_except GET { deny all; }" in conf
    assert 'if ($arg_src !~ "^[A-Za-z0-9_-]*$") { return 403; }' in conf
    assert 'if ($args !~ "^([a-z0-9_]+(=[^&]*)?(&|$))*$") { return 403; }' in conf
    assert 'if ($args ~ "(^|&)dst(=|&|$)") { return 403; }' in conf


def denied_api_pattern():
    return re.search(r'location ~ "([^"]+)" \{\s*return 403;', location("go2rtc.conf")).group(1)


def src_pattern():
    return re.search(r'\$arg_src !~ "([^"]+)"', location("go2rtc.conf")).group(1)


def args_pattern():
    return re.search(r'\$args !~ "([^"]+)"', location("go2rtc.conf")).group(1)


def dst_pattern():
    return re.search(r'\$args ~ "([^"]+)"', location("go2rtc.conf")).group(1)


@pytest.mark.parametrize(
    "path, denied",
    [
        ("/feeds/", False),
        ("/feeds/stream.html", False),
        ("/feeds/video-rtc.js", False),
        ("/feeds/api/ws", False),
        ("/feeds/api/streams", False),
        ("/feeds/api/frame.jpeg", False),
        ("/feeds/api/stream.mp4", False),
        ("/feeds/api/stream.m3u8", False),
        ("/feeds/api/stream.mjpeg", False),
        ("/feeds/api/hls/playlist.m3u8", False),
        ("/feeds/api/hls/segment.ts", False),
        ("/feeds/api/hls/segment.m4s", False),
        ("/feeds/api/hls/init.mp4", False),
        ("/feeds/api", True),
        ("/feeds/api/", True),
        ("/feeds/api/config", True),
        ("/feeds/api/log", True),
        ("/feeds/api/exit", True),
        ("/feeds/api/restart", True),
        ("/feeds/api/webrtc", True),
        ("/feeds/api/streams/extra", True),
        ("/feeds/api/streamsX", True),
        ("/feeds/api/hls/", True),
    ],
)
def test_feeds_denies_go2rtc_api_paths_beyond_viewing(path, denied):
    assert bool(re.search(denied_api_pattern(), path)) is denied


@pytest.mark.parametrize(
    "src, allowed",
    [
        ("picam_h265_detect", True),
        ("", True),
        ("exec:id", False),
        ("exec%3Aid", False),
        ("rtsp://192.168.1.20/live", False),
        ("ffmpeg:picam_h265_detect#video=h264", False),
        ("a b", False),
    ],
)
def test_feeds_accepts_only_stream_names_as_src(src, allowed):
    assert bool(re.search(src_pattern(), src)) is allowed


@pytest.mark.parametrize(
    "args, allowed",
    [
        ("", True),
        ("src=picam_h265_detect", True),
        ("src=a&src=b&mode=webrtc%2Cmse&width=50%25&background=false", True),
        ("id=Ab12cd", True),
        ("%73rc=rtsp://192.0.2.1/x", False),
        ("SRC=picam_h265_detect&src=rtsp://192.0.2.1/x", False),
        ("Src=rtsp://192.0.2.1/x", False),
        ("s+rc=rtsp://192.0.2.1/x", False),
    ],
)
def test_feeds_accepts_only_plain_parameter_names(args, allowed):
    """nginx matches $arg_src ignoring case and undecoded; go2rtc decodes names and is case-sensitive."""
    assert bool(re.search(args_pattern(), args)) is allowed


@pytest.mark.parametrize(
    "args, denied",
    [
        ("dst=0", True),
        ("dst=", True),
        ("dst", True),
        ("src=a&dst=b", True),
        ("dst=picam_h265_detect", True),
        ("src=a", False),
        ("xdst=1", False),
        ("dstx=1", False),
        ("", False),
    ],
)
def test_feeds_refuses_any_dst_parameter(args, denied):
    """nginx's if ($arg_dst) is false for dst= and dst=0, so the check matches the name in $args."""
    assert bool(re.search(dst_pattern(), args)) is denied


TM_CONTROL_DIR = "/usr/local/lib/traffic-monitor/tm-control"


def test_tm_control_wrapper_runs_only_the_root_owned_copy():
    script = render("script/ansible/roles/tmsetup/templates/tm-control/tm-control.j2", tmsetup_tm_control_dir=TM_CONTROL_DIR)
    assert script.splitlines()[0] == f"#!{TM_CONTROL_DIR}/venv/bin/python -EP"
    assert f'sys.path.insert(0, "{TM_CONTROL_DIR}/backend")' in script
    ast.parse(script)


SECRETS = {"go2rtc_rtsp_password": "s3cret"}
CREDENTIALED_INPUT = "rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/picam_h265_detect"


def go2rtc_config():
    return yaml.safe_load(render(
        "script/ansible/roles/tmsetup/templates/go2rtc.yaml.j2",
        tmsetup_go2rtc_rtsp_user="frigate", tmsetup_secrets=SECRETS,
    ))


def test_go2rtc_api_is_loopback_only_and_rtsp_needs_credentials():
    config = go2rtc_config()
    assert config["api"] == {"listen": "127.0.0.1:1984"}
    assert config["rtsp"] == {"listen": ":8554", "username": "frigate", "password": "s3cret"}
    assert set(config["streams"]) == {"picam_h265_detect", "picam_h265_detect_hr"}


def test_go2rtc_loads_no_webrtc_and_runs_only_allowed_commands():
    config = go2rtc_config()
    assert "webrtc" not in config["app"]["modules"]
    assert "webrtc" not in config
    for name, source in config["streams"].items():
        if source.startswith("exec:"):
            assert source[len("exec:"):].split()[0] in config["exec"]["allow_paths"], name


def test_new_frigate_configs_read_go2rtc_with_credentials():
    config = yaml.safe_load(render("container/frigate/config/config.yml.j2", tmsetup_detectors={}))
    assert config["cameras"]["picam_h265"]["ffmpeg"]["inputs"][0]["path"] == CREDENTIALED_INPUT


def test_new_frigate_configs_keep_object_snapshots_off_mqtt():
    """Frigate publishes a cropped snapshot of each object on MQTT unless the camera turns it off (#256)."""
    config = yaml.safe_load(render("container/frigate/config/config.yml.j2", tmsetup_detectors={}))
    assert config["cameras"]["picam_h265"]["mqtt"] == {"enabled": False}


def test_frigate_env_carries_the_go2rtc_credentials():
    lines = render(
        "container/frigate/frigate.env.j2",
        tmsetup_frigate_rtsp_password="password", tmsetup_frigate_mqtt_user="mqtt_user",
        tmsetup_frigate_mqtt_password="mqtt_pass", tmsetup_codedir="/opt/traffic-monitor",
        tmsetup_frigate_version="0.18.1",
        tmsetup_go2rtc_rtsp_user="frigate", tmsetup_secrets=SECRETS, tmsetup_mqtt_broker_login=NO_LOGIN,
    ).splitlines()
    assert "FRIGATE_GO2RTC_RTSP_USER=frigate" in lines
    assert "FRIGATE_GO2RTC_RTSP_PASSWORD=s3cret" in lines
    assert "FRIGATE_RTSP_PASSWORD=password" in lines  # operators' own variable is untouched


def test_pod_starts_even_if_its_network_unit_fails_once():
    """A .network reference makes Quadlet add Requires=tmnet-network.service, so one failed start of that unit
    at boot kept the pod down (#232). The pod names the network instead, and orders itself after the unit."""
    network = render("container/tmnet.network.j2").splitlines()
    name = next(line.split("=", 1)[1] for line in network if line.startswith("NetworkName="))
    pod = render("container/traffic-monitor.pod.j2", tmsetup_mqtt_lan_open=False).splitlines()
    assert f"Network={name}" in pod
    assert "Network=tmnet.network" not in pod
    assert "Wants=tmnet-network.service" in pod
    assert "After=tmnet-network.service" in pod


LOGIN = {"username": "tm", "password": "s3cret"}
NO_LOGIN = {"username": "", "password": ""}


def mqtt_lines(text):
    # Only the MQTT settings, so a failing assert can't print other values, such as the credential secret
    return [line for line in text.splitlines() if "MQTT_" in line and not line.startswith("#")]


def node_red_env(login):
    return mqtt_lines(render(
        "container/node-red-tm/node-red-tm.env.j2",
        ansible_facts={"hostname": "tm-test"}, tmsetup_raspberry_pi_serial="0000", tmsetup_tm_version="0.0.0",
        tmsetup_mqtt_broker_login=login,
    ))


def frigate_env(login):
    return mqtt_lines(render(
        "container/frigate/frigate.env.j2",
        tmsetup_frigate_rtsp_password="password", tmsetup_frigate_mqtt_user="mqtt_user",
        tmsetup_frigate_mqtt_password="mqtt_pass", tmsetup_codedir="/opt/traffic-monitor",
        tmsetup_frigate_version="0.18.1", tmsetup_go2rtc_rtsp_user="frigate", tmsetup_secrets=SECRETS,
        tmsetup_mqtt_broker_login=login,
    ))


def test_env_templates_render_the_broker_login():
    assert "TM_MQTT_BROKER_USERNAME=tm" in node_red_env(LOGIN)
    assert "TM_MQTT_BROKER_PASSWORD=s3cret" in node_red_env(LOGIN)
    assert "FRIGATE_MQTT_USER=tm" in frigate_env(LOGIN)
    assert "FRIGATE_MQTT_PASSWORD=s3cret" in frigate_env(LOGIN)


def test_env_templates_without_a_login():
    assert "TM_MQTT_BROKER_USERNAME=" in node_red_env(NO_LOGIN)
    assert "TM_MQTT_BROKER_PASSWORD=" in node_red_env(NO_LOGIN)
    assert "FRIGATE_MQTT_USER=mqtt_user" in frigate_env(NO_LOGIN)

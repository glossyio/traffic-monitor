"""Render tmsetup templates and check what the device gets. Off-device; no Ansible run needed."""

import ast
import re

import pytest
import yaml
from tmsetup_render import REPO, load_role_yaml, render

LOCATIONS = load_role_yaml("vars/main.yml")["tmsetup_revproxy_locations"]


def location(name):
    return render(f"container/revproxy/tm/locations/{name}.j2", **load_role_yaml("vars/main.yml"))


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
    """Retry for a few minutes while the old pod releases port 80 during an upgrade, then fail visibly."""
    unit = revproxy_unit()
    unit_section = unit[:unit.index("[Container]")]
    assert "StartLimitIntervalSec=300" in unit_section
    assert "StartLimitBurst=20" in unit_section
    assert "StartLimitIntervalSec=0" not in unit
    assert "RestartSec=5" in unit


@pytest.mark.parametrize("name", LOCATIONS)
def test_no_location_goes_through_host_containers_internal(name):
    assert "host.containers.internal" not in location(name)


# Which login check each app's location includes. Viewers may open the dashboards and Frigate; the Node-RED editor,
# the camera feeds, the database downloads, and Cockpit are for administrators.
APP_LOCATIONS = {
    "cockpit.conf": "auth-admin",
    "dashboard.conf": "auth-viewer",
    "frigate.conf": "auth-viewer",
    "go2rtc.conf": "auth-admin",
    "legacy-ui.conf": "auth-viewer",
    "nodered.conf": "auth-admin",
    "storefiles.conf": "auth-admin",
}
TM_CONTROL_LOCATIONS = {"tm-control-ui.conf", "tm-control-api.conf", "tm-control-auth.conf"}
IDENTITY_VARIABLES = ["tm_user", "tm_role", "tm_nr_token", "tm_frigate_secret", "tm_redirect"]


def snippet(name):
    return render(f"container/revproxy/tm/snippets/{name}.j2")


def location_block(conf, header):
    """One location block's text, from its header to the first closing brace at the start of a line."""
    start = conf.index(header)
    return conf[start:conf.index("\n}", start) + 2]


def test_every_listed_location_is_an_app_or_tm_control():
    """A new app location must be added to APP_LOCATIONS, so it can't ship without a login check."""
    assert set(LOCATIONS) == set(APP_LOCATIONS) | TM_CONTROL_LOCATIONS


@pytest.mark.parametrize("name, auth", APP_LOCATIONS.items())
def test_every_app_location_includes_exactly_one_auth_snippet(name, auth):
    conf = location(name)
    assert conf.count("/etc/nginx/tm/snippets/auth-") == 1
    assert f"include /etc/nginx/tm/snippets/{auth}.conf;" in conf


def test_feeds_checks_the_login_before_its_rules_and_the_api_denial_stays_as_it_is():
    conf = location("go2rtc.conf")
    feeds = location_block(conf, "location /feeds/ {")
    assert feeds.index("include /etc/nginx/tm/snippets/auth-admin.conf;") < feeds.index("if (")
    denied = conf[conf.index("location ~ "):]
    assert "auth-" not in denied and "proxy_pass" not in denied


@pytest.mark.parametrize("name", list(APP_LOCATIONS))
def test_no_app_location_adds_its_own_headers(name):
    """The snippet's add_header Set-Cookie must be the location's only add_header, or the two would interact."""
    assert "add_header" not in location(name)


def test_tm_control_locations_are_listed_and_the_home_page_is_gone():
    nginx_conf = render("container/revproxy/nginx.conf.j2")
    assert TM_CONTROL_LOCATIONS <= set(LOCATIONS)
    assert "location / " not in nginx_conf
    assert "include /etc/nginx/tm/locations/*.conf;" in nginx_conf
    assert not (REPO / "container/revproxy/html/index.html.j2").exists()


def test_snippets_are_listed():
    assert load_role_yaml("vars/main.yml")["tmsetup_revproxy_snippets"] == [
        "proxy-common.conf", "auth-viewer.conf", "auth-admin.conf",
    ]


@pytest.mark.parametrize("name", ["auth-viewer.conf", "auth-admin.conf"])
def test_auth_snippets_set_every_identity_variable_and_the_error_pages(name):
    conf = snippet(name)
    for variable in IDENTITY_VARIABLES:
        assert f"auth_request_set ${variable} $upstream_http_x_{variable};" in conf
    assert "error_page 401 = @tm_login;" in conf
    # Only a failed check (auth_request's 500) gets the rescue page; an app that is down keeps nginx's 502/504
    assert "error_page 500 =503 /unavailable.html;" in conf.splitlines()
    assert not [line for line in conf.splitlines() if line.startswith("error_page") and "502" in line]


@pytest.mark.parametrize("name", ["auth-viewer.conf", "auth-admin.conf"])
def test_auth_snippets_pass_the_refreshed_session_cookie_to_the_browser(name):
    """auth_request drops the subrequest's Set-Cookie, so verify's rolling refresh is copied onto the response.
    nginx skips an add_header whose value is empty, so a request without a refresh gets no Set-Cookie from it."""
    conf = snippet(name)
    assert "auth_request_set $tm_set_cookie $upstream_http_set_cookie;" in conf
    assert "add_header Set-Cookie $tm_set_cookie;" in conf.splitlines()  # without "always": 2xx and 3xx only


def test_viewer_and_admin_snippets_differ_only_in_the_auth_location():
    viewer = snippet("auth-viewer.conf").splitlines()
    admin = snippet("auth-admin.conf").splitlines()
    assert len(viewer) == len(admin)
    assert [(v, a) for v, a in zip(viewer, admin) if v != a] == [("auth_request /_auth;", "auth_request /_auth_admin;")]


@pytest.mark.parametrize("path, role", [("/_auth", "viewer"), ("/_auth_admin", "admin")])
def test_auth_locations_are_internal_and_name_the_role(path, role):
    block = location_block(location("tm-control-auth.conf"), f"location = {path} {{")
    assert "internal;" in block
    assert "proxy_pass http://127.0.0.1:8090/api/v1/auth/verify;" in block
    assert f"proxy_set_header X-TM-Required-Role {role};" in block
    assert "proxy_set_header X-Original-URI $request_uri;" in block
    assert "proxy_method GET;" in block
    assert "proxy_pass_request_body off;" in block
    assert 'proxy_set_header Content-Length "";' in block


def test_failed_logins_redirect_and_the_rescue_page_is_internal():
    conf = location("tm-control-auth.conf")
    assert "location @tm_login { return 302 $tm_redirect; }" in conf
    assert "location = /unavailable.html { internal; root /usr/share/nginx/html; }" in conf


def test_verify_is_unreachable_from_the_network():
    assert "location = /api/v1/auth/verify { return 404; }" in location("tm-control-api.conf")


def test_api_and_logout_are_proxied_to_tm_control_on_loopback():
    conf = location("tm-control-api.conf")
    api = location_block(conf, "location /api/ {")
    assert "proxy_pass http://127.0.0.1:8090/api/;" in api
    assert "include /etc/nginx/tm/snippets/proxy-common.conf;" in api
    logout = conf[conf.index("location = /logout {"):]
    assert "proxy_pass http://127.0.0.1:8090/logout;" in logout
    assert "include /etc/nginx/tm/snippets/proxy-common.conf;" in logout
    assert "auth-" not in conf  # tm-control checks its own API calls


def test_ui_root_serves_the_built_app_with_history_fallback():
    """The UI is built into the image, outside the bind-mounted html directory, and stays open for login and setup."""
    conf = location("tm-control-ui.conf")
    assert "location / {" in conf
    assert "root /usr/share/nginx/ui;" in conf
    assert "try_files $uri $uri/ /index.html;" in conf
    assert "auth-" not in conf


def test_unavailable_page_names_cockpit_and_the_service():
    page = render(
        "container/revproxy/html/unavailable.html.j2",
        tmsetup_homepage_colors=load_role_yaml("defaults/main.yml")["tmsetup_homepage_colors"],
        tmsetup_homepage_font="Helvetica",
        ansible_facts={"hostname": "tm"},
    )
    assert "http://tm:9090/" in page
    assert "tm-control.service" in page
    assert "sudo systemctl restart tm-control.service" in page
    assert "<script" not in page


@pytest.mark.parametrize("name", LOCATIONS)
def test_no_location_carries_a_secret_value(name):
    assert "tmsetup_secrets" not in (REPO / f"container/revproxy/tm/locations/{name}.j2").read_text()


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


TM_CONTROL_TEMPLATES = "script/ansible/roles/tmsetup/templates/tm-control"


def tm_control_unit():
    return render(
        f"{TM_CONTROL_TEMPLATES}/tm-control.service.j2",
        tmsetup_codeowner="tmadmin", tmsetup_codegroup="tmadmin", tmsetup_secrets_dir="/etc/traffic-monitor/secrets",
        tmsetup_etc_dir="/etc/traffic-monitor", tmsetup_tm_control_port=8090,
    ).splitlines()


def test_tm_control_runs_as_the_code_owner_in_a_sandbox():
    unit = tm_control_unit()
    for line in ["User=tmadmin", "Group=tmadmin", "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes",
                 "PrivateTmp=yes", "StateDirectory=tm-control", "StateDirectoryMode=0700", "RuntimeDirectory=tm-control",
                 "RuntimeDirectoryMode=0700", "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"]:
        assert line in unit


def test_tm_control_reads_the_journal_for_job_status():
    """A finished oneshot job unit is unloaded, so tm-control reads PID 1's job-end entries from the journal."""
    assert "SupplementaryGroups=systemd-journal" in tm_control_unit()


def test_tm_control_reads_the_files_tmsetup_writes():
    unit = tm_control_unit()
    assert "ExecStart=/usr/local/bin/tm-control serve" in unit
    assert "Environment=TM_CONTROL_SECRETS_DIR=/etc/traffic-monitor/secrets" in unit
    assert "Environment=TM_CONTROL_MANIFEST=/etc/traffic-monitor/manifest.json" in unit


def test_tm_control_binds_to_loopback_only():
    assert "Environment=TM_CONTROL_BIND=127.0.0.1:8090" in tm_control_unit()


def test_tm_control_has_no_write_paths_outside_its_state():
    assert not any(line.startswith("ReadWritePaths=") for line in tm_control_unit())


def test_tm_control_runtime_directory_is_removed_when_it_stops():
    """Job requests live in /run/tm-control/jobs; systemd's default removes the directory when the service stops."""
    assert not any(line.startswith("RuntimeDirectoryPreserve=") for line in tm_control_unit())


def tm_job_unit():
    return render(
        f"{TM_CONTROL_TEMPLATES}/tm-job-system-password.service.j2",
        tmsetup_tm_control_dir=TM_CONTROL_DIR, tmsetup_libexec_dir="/usr/local/libexec/traffic-monitor",
        tmsetup_etc_dir="/etc/traffic-monitor",
    )


def test_job_unit_is_a_root_oneshot_without_install():
    unit = tm_job_unit()
    lines = unit.splitlines()
    assert "Type=oneshot" in lines
    assert "[Install]" not in unit
    assert not any(line.startswith(("User=", "DynamicUser=")) for line in lines)
    assert (f"ExecStart={TM_CONTROL_DIR}/venv/bin/python -EP /usr/local/libexec/traffic-monitor/tm-job-system-password"
            in lines)
    assert "Environment=TM_CONTROL_MANIFEST=/etc/traffic-monitor/manifest.json" in lines


def test_job_unit_never_hits_a_start_limit():
    """A start refused by the start limit would leave the job queued in tm-control."""
    lines = tm_job_unit().splitlines()
    assert "StartLimitIntervalSec=0" in lines[lines.index("[Unit]"):lines.index("[Service]")]


def polkit_rules():
    return render(
        f"{TM_CONTROL_TEMPLATES}/50-traffic-monitor.rules.j2",
        tmsetup_codeowner="tmadmin",
        tmsetup_tm_control_polkit=load_role_yaml("vars/main.yml")["tmsetup_tm_control_polkit"],
    )


def test_polkit_rules_allow_only_named_units_for_the_code_owner():
    rules = polkit_rules()
    assert 'subject.user !== "tmadmin"' in rules
    assert 'action.id === "org.freedesktop.systemd1.manage-units"' in rules
    assert '"tm-job-system-password.service"' in rules
    assert '["start", "stop", "restart"]' in rules
    assert "timedate1" not in rules and "login1" not in rules
    assert rules.count("polkit.Result.YES") == 1


def test_polkit_allowlist_covers_the_traffic_monitor_units_only():
    polkit = load_role_yaml("vars/main.yml")["tmsetup_tm_control_polkit"]
    assert polkit["units"] == [
        "traffic-monitor.service", "frigate.service", "node-red-tm.service", "plate-recognizer.service",
        "revproxy.service", "go2rtc_server.service", "tm-job-system-password.service",
    ]
    assert polkit["unit_verbs"] == ["start", "stop", "restart"]


def js_brackets_balance(source):
    """A cheap syntax check without node: brackets nest and close, and every string literal closes on its line.
    Whole-line // comments are skipped."""
    source = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))
    pairs, stack, quote, escaped = {")": "(", "]": "[", "}": "{"}, [], None, False
    for char in source:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            elif char == "\n":
                return False
        elif char in "\"'":
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False
    return quote is None and not stack


def test_polkit_rules_parse_as_javascript():
    assert js_brackets_balance(polkit_rules())
    assert not js_brackets_balance('polkit.addRule(function () { return "x; });')
    assert not js_brackets_balance("polkit.addRule(function () { return [1, 2); });")


def test_homepage_colors_are_css_hex_colors():
    """The colors go into the install manifest and the UI theme."""
    for name, value in load_role_yaml("defaults/main.yml")["tmsetup_homepage_colors"].items():
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), name

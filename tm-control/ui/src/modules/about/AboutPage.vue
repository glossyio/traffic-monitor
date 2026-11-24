<!--
  The About page: what the project is, what it is built on, and the license notices, for every signed-in user.
  It asks the device for nothing and fetches nothing, so it reads the same on the hotspot with no internet; the
  links that leave the device are extras. The credits are rows of credits.json (tests check them against the
  dependencies); this file holds the sentences and the order of the groups.
-->
<script setup lang="ts">
import credits from './credits.json'
import RoadParade from './RoadParade.vue'

// Every link that leaves the device opens in a new tab and sends no referrer
const OUTSIDE = { class: 'text-primary', target: '_blank', rel: 'noopener noreferrer' }

const REPO = 'https://github.com/glossyio/traffic-monitor'

const PLACES = [
  { text: 'trafficmonitor.ai', href: 'https://www.trafficmonitor.ai/' },
  { text: 'Documentation', href: 'https://docs.trafficmonitor.ai/' },
  { text: 'Source code on GitHub', href: REPO },
  { text: 'Roadway Biome', href: 'https://www.roadwaybiome.com/' },
]

// The groups of "Also on this device", in the order they are shown
const GROUPS = [
  { id: 'video', title: 'Video and detection' },
  { id: 'data', title: 'Data and dashboards' },
  { id: 'app', title: 'The control app' },
  { id: 'device', title: 'The device' },
]

const builtOn = credits.filter((row) => row.group === 'built-on')
const rowsOf = (group: string) => credits.filter((row) => row.group === group)
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">About</h1>

    <p class="text-body-1">
      Traffic Monitor is an open source roadway counter and speed monitor. It counts people walking, bicycles, and
      vehicles and measures speeds, on the device, with a camera and a radar. It is maintained by Roadway Biome, which
      also sells assembled units and runs the server that units can share data with.
    </p>
    <!-- A wrapping row, so four links fit a 360 px phone on two lines -->
    <div class="d-flex flex-wrap ga-x-6 ga-y-2 my-4 text-body-1">
      <a v-for="place in PLACES" :key="place.href" :href="place.href" v-bind="OUTSIDE">{{ place.text }}</a>
    </div>
    <p class="text-body-1">
      Software versions are on the <router-link to="/device" class="text-primary">Device page</router-link>.
    </p>

    <section class="mt-10">
      <h2 class="text-h6 mb-2">Built on</h2>
      <v-list class="bg-transparent">
        <v-list-item v-for="row in builtOn" :key="row.name" class="px-0">
          <div class="d-flex flex-wrap align-baseline ga-x-3">
            <a :href="row.url" v-bind="OUTSIDE" class="font-weight-medium">{{ row.name }}</a>
            <span class="text-body-2 text-medium-emphasis">{{ row.license }}</span>
          </div>
          <div class="text-body-1">{{ row.does }}</div>
        </v-list-item>
      </v-list>
    </section>

    <section class="mt-10">
      <h2 class="text-h6 mb-2">Also on this device</h2>
      <div v-for="group in GROUPS" :key="group.id" class="mb-4">
        <h3 class="text-subtitle-1 font-weight-medium">{{ group.title }}</h3>
        <v-list class="bg-transparent" density="compact">
          <v-list-item v-for="row in rowsOf(group.id)" :key="row.name" class="px-0">
            <!-- The name, then its license; a long license wraps to its own line on a narrow screen -->
            <div class="d-flex flex-wrap align-baseline ga-x-3">
              <a :href="row.url" v-bind="OUTSIDE">{{ row.name }}</a>
              <span class="text-body-2 text-medium-emphasis">{{ row.license }}</span>
            </div>
            <div v-if="'note' in row" class="text-body-2">{{ row.note }}</div>
          </v-list-item>
        </v-list>
      </div>
    </section>

    <section class="mt-10">
      <h2 class="text-h6 mb-2">Map</h2>
      <p class="text-body-1">
        <a href="https://openfreemap.org" v-bind="OUTSIDE">OpenFreeMap</a>
        <a href="https://www.openmaptiles.org/" v-bind="OUTSIDE" class="ms-2">© OpenMapTiles</a>
        Data from <a href="https://www.openstreetmap.org/copyright" v-bind="OUTSIDE">OpenStreetMap</a>
      </p>
      <p class="text-body-1">
        The Location page's map comes from OpenFreeMap when your browser is online. The map data is available under the
        Open Database License.
      </p>
    </section>

    <section class="mt-10">
      <h2 class="text-h6 mb-2">Licenses and source code</h2>
      <p class="text-body-1 mb-3">
        Copyright © Traffic Monitor contributors. Traffic Monitor is free software under the
        <a :href="`${REPO}/blob/main/LICENSE`" v-bind="OUTSIDE">GNU General Public License, version 3</a>. It comes with no
        warranty. Its source code is at <a :href="REPO" v-bind="OUTSIDE">github.com/glossyio/traffic-monitor</a>.
      </p>
      <p class="text-body-1 mb-3">
        The video tool on this device, FFmpeg, is a Raspberry Pi build with the x264 and x265 encoders, under the GNU
        General Public License, version 2 or later. The recipe that builds it is in Traffic Monitor's source code.
      </p>
      <p class="text-body-1 mb-3">
        The licenses of Raspberry Pi OS's own packages are on the device, in <code>/usr/share/doc</code>.
      </p>
      <p class="text-body-1 mb-3">
        For the source code of any open source software on a device you bought, write to
        <a href="mailto:info@roadwaybiome.com" class="text-primary">info@roadwaybiome.com</a>.
      </p>
      <!-- Same origin, so no https:// address; a text file, so it opens beside this page -->
      <p class="text-body-1 mb-3">
        <a href="/third-party-licenses.txt" v-bind="OUTSIDE">License texts of the libraries built into this app</a>
      </p>
      <p class="text-body-2 text-medium-emphasis">
        Frigate, Frigate NVR, and Frigate+ are trademarks of Frigate, Inc. Node-RED is a trademark of the OpenJS
        Foundation. Raspberry Pi is a trademark of Raspberry Pi Ltd. FFmpeg is a trademark of Fabrice Bellard. These
        projects don't endorse Traffic Monitor.
      </p>
    </section>

    <RoadParade />
  </div>
</template>

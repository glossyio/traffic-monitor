// Starts the app: loads the device's setup status (which carries its colors), builds the theme, and shows the page.
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { createAppRouter } from './router'
import { useSession } from './stores/session'
import { createAppVuetify } from './theme'

async function start() {
  const pinia = createPinia()
  const session = useSession(pinia)
  await session.load() // on failure, App.vue says so and offers to try again
  const vuetify = createAppVuetify(session.status?.theme.colors)
  createApp(App).use(pinia).use(createAppRouter()).use(vuetify).mount('#app')
}

void start()

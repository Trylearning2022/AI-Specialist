import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import { initAuth } from './auth'
import { initTheme } from './ui'
import './style.css'

initTheme()

initAuth()
  .catch((e) => { document.body.innerHTML = `<p style="padding:2rem">Không khởi tạo được xác thực: ${e.message}</p>`; throw e })
  .then(() => createApp(App).use(router).mount('#app'))

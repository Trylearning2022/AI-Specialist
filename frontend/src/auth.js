// Xác thực: Keycloak (OIDC, PKCE) trong vận hành; tài khoản thử nghiệm khi AUTH_MODE=dev.
import Keycloak from 'keycloak-js'
import { reactive } from 'vue'

export const auth = reactive({ ready: false, mode: 'oidc', user: null, devUsers: [], error: '' })
let kc = null

export async function initAuth() {
  const cfg = await fetch('/api/config').then((r) => r.json())
  auth.mode = cfg.auth_mode
  if (cfg.auth_mode === 'dev') {
    auth.devUsers = cfg.dev_users
    const saved = sessionStorage.getItem('devUser')
    if (saved) await loadMe()
    auth.ready = true
    return
  }
  const issuer = new URL(cfg.oidc_issuer)
  const [, base, realm] = issuer.pathname.match(/^(.*)\/realms\/([^/]+)/) || []
  kc = new Keycloak({ url: issuer.origin + base, realm, clientId: cfg.oidc_client_id })
  await kc.init({ onLoad: 'login-required', pkceMethod: 'S256', checkLoginIframe: false })
  setInterval(() => kc.updateToken(60).catch(() => kc.login()), 30000)
  await loadMe()
  auth.ready = true
}

export async function token() {
  if (auth.mode === 'dev') return 'dev-' + (sessionStorage.getItem('devUser') || '')
  await kc.updateToken(30)
  return kc.token
}

export async function devLogin(name) {
  sessionStorage.setItem('devUser', name)
  await loadMe()
}

export function logout() {
  if (auth.mode === 'dev') { sessionStorage.removeItem('devUser'); auth.user = null; return }
  kc.logout({ redirectUri: location.origin })
}

async function loadMe() {
  const r = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + (await token()) } })
  if (!r.ok) { auth.user = null; auth.error = 'Đăng nhập không thành công'; return }
  auth.user = await r.json()
}

export const has = (...roles) => !!auth.user && roles.some((r) => auth.user.roles.includes(r))

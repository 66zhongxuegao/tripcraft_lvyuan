import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 用户身份与多用户：切换用户即切换整套隔离数据 */
const LS_USER = 'tc-user'
const LS_USERS = 'tc-users'

function loadUsers() {
  try {
    const a = JSON.parse(localStorage.getItem(LS_USERS) || '[]')
    if (Array.isArray(a) && a.length) {
      return a.map((u: any) => ({ id: u.id, name: String(u.name || '').startsWith('存档') ? String(u.name).replace('存档', '用户') : (u.name || u.id) }))
    }
  } catch {}
  return [{ id: 'u-demo', name: '用户 1' }]
}

export const useUserStore = defineStore('user', () => {
  const consultantName = ref('演示定制师')
  const companyName = ref('')
  const userId = ref(localStorage.getItem(LS_USER) || 'u-demo')
  const users = ref<{ id: string; name: string }[]>(loadUsers())
  const inbound = ref(false)

  function setProfile(name: string, company = '') {
    consultantName.value = name || '演示定制师'
    companyName.value = company
  }

  function switchUser(id: string) {
    if (!id) return
    userId.value = id
    localStorage.setItem(LS_USER, id)
  }

  function addUser() {
    const id = 'u-' + Date.now().toString(36)
    const name = '用户 ' + (users.value.length + 1)
    users.value = [...users.value, { id, name }]
    localStorage.setItem(LS_USERS, JSON.stringify(users.value))
    switchUser(id)
    return id
  }

  return { consultantName, companyName, userId, users, inbound, setProfile, switchUser, addUser }
})

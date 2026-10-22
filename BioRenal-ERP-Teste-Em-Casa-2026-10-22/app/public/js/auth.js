window.BioRenalAuth = {
  user: null,
  csrf: '',
  ready: null,
  async logout() {
    await this.ready;
    await fetch('/api/auth/logout', {method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-CSRF-Token':this.csrf},body:'{}'});
    location.replace('/login.html');
  },
};
window.BioRenalAuth.ready = (async () => {
  const response = await fetch('/api/auth/status',{cache:'no-store',credentials:'same-origin'});
  if (!response.ok) throw new Error('Não foi possível verificar a sessão.');
  const state = await response.json();
  if (!state.authenticated) {location.replace('/login.html'); return;}
  window.BioRenalAuth.user=state.usuario;
  window.BioRenalAuth.csrf=state.csrf_token;
  document.documentElement.dataset.role=state.usuario.role;
  document.getElementById('auth-user-name').textContent=state.usuario.display_name;
  document.getElementById('auth-manage-button').hidden=state.usuario.role!=='ADMIN';
})();

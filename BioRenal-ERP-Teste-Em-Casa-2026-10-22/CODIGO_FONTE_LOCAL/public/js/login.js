const statusEl = document.getElementById('auth-message');
function showMessage(message, success=false) { statusEl.textContent = message; statusEl.classList.toggle('success', success); }
async function request(path, body) {
  const response = await fetch(path, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.erro || 'Não foi possível concluir a operação.');
  return data;
}
async function initLogin() {
  try {
    const response = await fetch('/api/auth/status', {cache:'no-store', credentials:'same-origin'});
    const state = await response.json();
    if (state.authenticated) { location.replace('/'); return; }
    if (state.configured) {
      document.getElementById('login-form').hidden = false;
    } else if (['localhost','127.0.0.1','::1'].includes(location.hostname)) {
      document.getElementById('auth-title').textContent = 'Criar administrador inicial';
      document.getElementById('auth-description').textContent = 'Este cadastro inicia a área de login. Guarde a senha em local seguro.';
      document.getElementById('setup-form').hidden = false;
    } else {
      showMessage('O administrador inicial precisa ser criado no computador principal antes do acesso pela rede.');
    }
  } catch (_) { showMessage('Não foi possível conectar ao sistema neste computador.'); }
}
document.getElementById('login-form').addEventListener('submit', async event => {
  event.preventDefault(); const form=event.currentTarget; const button=form.querySelector('button');
  button.disabled=true; showMessage('');
  try { await request('/api/auth/login', Object.fromEntries(new FormData(form).entries())); location.replace('/'); }
  catch(error) { showMessage(error.message); button.disabled=false; }
});
document.getElementById('setup-form').addEventListener('submit', async event => {
  event.preventDefault(); const form=event.currentTarget; const values=Object.fromEntries(new FormData(form).entries());
  if (values.password !== values.confirm_password) { showMessage('As senhas não coincidem.'); return; }
  const button=form.querySelector('button'); button.disabled=true; showMessage('');
  try {
    await request('/api/auth/setup', values);
    document.getElementById('setup-form').hidden=true;
    document.getElementById('login-form').hidden=false;
    document.getElementById('auth-title').textContent='Entrar no sistema';
    document.querySelector('#login-form input[name="username"]').value=values.username;
    showMessage('Administrador criado. Entre com sua senha.',true);
  } catch(error) { showMessage(error.message); }
  finally { button.disabled=false; }
});
initLogin();

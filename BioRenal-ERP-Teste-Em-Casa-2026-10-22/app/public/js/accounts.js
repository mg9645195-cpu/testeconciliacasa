const page = document.body.dataset.page;
let csrfToken = '';
let userRows = [];
const messageEl = document.getElementById('auth-message');
function message(text,success=false) { messageEl.textContent=text; messageEl.classList.toggle('success',success); }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
async function post(path,body) {
  const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)});
  const data=await response.json(); if (!response.ok) throw new Error(data.erro || 'Operação não concluída.'); return data;
}
async function loadUsers() {
  const response=await fetch('/api/auth/users',{cache:'no-store'});
  if (!response.ok) throw new Error('Não foi possível listar usuários.');
  userRows=(await response.json()).usuarios;
  document.getElementById('users-table').innerHTML=`<thead><tr><th>Nome</th><th>Usuário</th><th>Perfil</th><th>Situação</th><th></th></tr></thead><tbody>${userRows.map(u=>`<tr><td>${esc(u.display_name)}</td><td>${esc(u.username)}</td><td>${esc(u.role)}</td><td>${u.active?'Ativo':'Bloqueado'}</td><td><button type="button" data-edit="${u.id}" style="padding:6px 10px">Editar</button></td></tr>`).join('')}</tbody>`;
  document.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',()=>editUser(Number(button.dataset.edit))));
}
function editUser(id) {
  const row=userRows.find(u=>u.id===id); if (!row) return;
  const form=document.getElementById('user-form');
  for (const key of ['id','display_name','username','role']) form.elements[key].value=row[key];
  form.elements.password.value=''; form.elements.active.checked=Boolean(row.active);
  document.getElementById('form-title').textContent=`Editar ${row.display_name}`;
  document.getElementById('password-hint').textContent='(deixe vazio para manter a senha)';
  form.scrollIntoView({behavior:'smooth'});
}
function clearForm() {
  const form=document.getElementById('user-form'); form.reset(); form.elements.id.value='';
  document.getElementById('form-title').textContent='Novo usuário';
  document.getElementById('password-hint').textContent='(mínimo 12 caracteres)';
}
async function init() {
  try {
    const response=await fetch('/api/auth/status',{cache:'no-store'});
    const state=await response.json();
    if (!state.authenticated) {location.replace('/login.html');return;}
    csrfToken=state.csrf_token;
    if (page==='users') {
      if (state.usuario.role!=='ADMIN') {location.replace('/');return;}
      await loadUsers();
    } else document.getElementById('account-name').textContent=state.usuario.display_name;
  } catch(error) {message(error.message);}
}
if (page==='users') {
  document.getElementById('clear-form').addEventListener('click',clearForm);
  document.getElementById('user-form').addEventListener('submit',async event=>{
    event.preventDefault(); const form=event.currentTarget;
    const body=Object.fromEntries(new FormData(form).entries());
    body.id=body.id ? Number(body.id) : 0; body.active=form.elements.active.checked;
    if (!body.id && !body.password) return message('Defina a senha inicial com pelo menos 12 caracteres.');
    try {await post('/api/auth/users',body); clearForm(); await loadUsers(); message('Usuário salvo.',true);}
    catch(error) {message(error.message);}
  });
} else {
  document.getElementById('password-form').addEventListener('submit',async event=>{
    event.preventDefault(); const values=Object.fromEntries(new FormData(event.currentTarget).entries());
    if (values.new_password!==values.confirm_password) return message('As novas senhas não coincidem.');
    try {await post('/api/auth/password',values); location.replace('/login.html');}
    catch(error) {message(error.message);}
  });
}
init();

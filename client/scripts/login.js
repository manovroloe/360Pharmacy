(() => {
  const $ = (query, scope=document) => scope.querySelector(query);
  const $$ = (query, scope=document) => [...scope.querySelectorAll(query)];
  const pendingKey = '360pharmacy_verify_email_v5';
  const descriptions = {
    signin: ['WELCOME BACK', 'Sign in to your account', 'One secure login for customers and every pharmacy role.'],
    signup: ['JOIN 360 PHARMACY', 'Create a customer account', 'Verify your email to start shopping and tracking orders.'],
    verify: ['EMAIL VERIFICATION', 'Verify your email', 'Enter the verification code sent by Supabase Auth.'],
    forgot: ['ACCOUNT RECOVERY', 'Reset your password', 'Receive a secure email link and create a new password.'],
    newpass: ['SET YOUR PASSWORD', 'Secure your account', 'Create the password you will use on this shared login page.']
  };
  let mode='signin';
  function icons(){window.lucide?.createIcons();}
  function notify(message, error=false) {
    const box=$('#loginAlert');
    box.textContent=message;
    box.classList.remove('hidden');
    box.classList.toggle('error',error);
  }
  function clearMessage(){const box=$('#loginAlert');box.classList.add('hidden');box.textContent='';}
  function switchMode(next) {
    if(!descriptions[next]) next='signin';
    mode=next;
    const [eyebrow,title,desc]=descriptions[next];
    $('#modeEyebrow').textContent=eyebrow;
    $('#modeTitle').textContent=title;
    $('#modeDescription').textContent=desc;
    $$('[data-panel]').forEach(el=>el.classList.toggle('hidden', el.dataset.panel!==next));
    $$('#loginTabs [data-mode]').forEach(el=>el.classList.toggle('active',el.dataset.mode===next));
    $('#loginTabs').classList.toggle('hidden',!['signin','signup'].includes(next));
    clearMessage();icons();
  }
  function pendingEmail(){return sessionStorage.getItem(pendingKey)||'';}
  function setPending(email){sessionStorage.setItem(pendingKey,email);$('#verifyAddress').textContent=email;$('#verifyForm [name=email]').value=email;}
  function safeNext() {
    const value=new URLSearchParams(location.search).get('next')||'';
    return value.startsWith('/')&&!value.startsWith('//')&&!value.includes('\\') ? value : '';
  }
  function routeForRole(role){
    const assignedRole = String(role || '').trim().toLowerCase();
    // Never use ?next=/ (storefront) for an Administrator or another staff role.
    if (['admin', 'pharmacist', 'merchandiser', 'delivery'].includes(assignedRole)) return '/workspace';
    if (assignedRole === 'customer') return safeNext() && !safeNext().startsWith('/workspace') ? safeNext() : '/';
    // Do not silently treat an unknown role as a customer.
    return '/login';
  }
  async function completeSession(result) {
    API.setSession(result);
    const profile=result.profile || (await API.me()).profile;
    sessionStorage.removeItem(pendingKey);
    location.replace(routeForRole(profile.role));
  }
  function withBusy(form, fn) {
    form.addEventListener('submit',async ev=>{
      ev.preventDefault();
      const button=$('button[type=submit]',form);
      button.disabled=true;
      try{await fn(Object.fromEntries(new FormData(form)));}
      catch(err){notify(err.message||'Something went wrong. Please retry.',true);}
      finally{button.disabled=false;}
    });
  }
  async function processEmailLink(){
    const fragment=new URLSearchParams(location.hash.replace(/^#/,''));
    const type=fragment.get('type') || new URLSearchParams(location.search).get('type');
    const access=fragment.get('access_token');
    const refresh=fragment.get('refresh_token');
    const error=fragment.get('error_description');
    // Remove sensitive session credentials from browser history immediately.
    if(location.hash)history.replaceState({},'',location.pathname+location.search);
    if(error){switchMode('signin');notify(error.replaceAll('+',' '),true);return true;}
    if(access && refresh){
      API.setSession({access_token:access,refresh_token:refresh,expires_in:Number(fragment.get('expires_in')||3600)});
      if(type==='invite'||type==='recovery'){
        $('#passwordNotice').textContent=type==='invite'
          ? 'Your staff invitation is confirmed. Choose a private password; the Admin has already assigned your position.'
          : 'Your password recovery link was verified. Choose a new password.';
        switchMode('newpass');return true;
      }
      try {const me=await API.me();location.replace(routeForRole(me.profile.role));}
      catch(err){switchMode('signin');notify(err.message,true);}
      return true;
    }
    return false;
  }
  async function start(){
    $$('[data-mode]').forEach(btn=>btn.addEventListener('click',()=>switchMode(btn.dataset.mode)));
    $$('[data-toggle]').forEach(btn=>btn.addEventListener('click',()=>{
      const field=document.getElementById(btn.dataset.toggle);
      if(field)field.type=field.type==='password'?'text':'password';
    }));
    withBusy($('#signinForm'),async data=>{
      const result=await API.login({email:data.email,password:data.password});
      await completeSession(result);
    });
    withBusy($('#signupForm'),async data=>{
      if(data.password!==data.confirm_password)throw new Error('Passwords do not match.');
      const response=await API.register({full_name:data.full_name,email:data.email,password:data.password});
      setPending(response.email||data.email);
      switchMode('verify');notify('Check your email for the verification code.');
    });
    withBusy($('#verifyForm'),async data=>{
      const response=await API.verifyEmail({email:data.email,token:data.token});
      sessionStorage.removeItem(pendingKey);
      switchMode('signin');$('#signinForm [name=email]').value=data.email;
      notify('Email verified! You may now sign in.');
    });
    $('#resendCode').addEventListener('click',async()=>{
      const email=$('#verifyForm [name=email]').value.trim();
      if(!email){notify('Please enter your email address.',true);return;}
      try{await API.resendVerification({email});notify('A new verification email has been requested.');}
      catch(err){notify(err.message,true);}
    });
    withBusy($('#forgotForm'),async data=>{
      await API.forgotPassword({email:data.email});
      notify('If this email belongs to an account, a recovery link has been sent.');
    });
    withBusy($('#newPasswordForm'),async data=>{
      if(data.new_password!==data.confirm_password)throw new Error('Passwords do not match.');
      await API.updatePassword({new_password:data.new_password});
      const me=await API.me();
      location.replace(routeForRole(me.profile.role));
    });
    if(await processEmailLink())return;
    const requested=new URLSearchParams(location.search).get('mode');
    if(requested==='signup') switchMode('signup');
    else if(requested==='verify'){switchMode('verify');if(pendingEmail())setPending(pendingEmail());}
    else if(requested==='forgot') switchMode('forgot');
    else if(pendingEmail()){switchMode('verify');setPending(pendingEmail());}
    if(mode!=='signup'&&mode!=='verify'&&mode!=='forgot' && await API.ready()){
      try{const me=await API.me();location.replace(routeForRole(me.profile.role));}
      catch(_){API.clearSession();}
    }
    icons();
  }
  window.addEventListener('DOMContentLoaded',start);
})();

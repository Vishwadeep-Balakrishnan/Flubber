document.getElementById('practice-form').addEventListener('submit',event=>{
  event.preventDefault();
  const name=document.getElementById('name').value.trim() || 'Guest';
  const frequency=document.getElementById('frequency').value;
  const reminders=document.getElementById('reminders').checked;
  const result=document.getElementById('result');
  result.textContent=`Saved for ${name}. Updates: ${frequency}. Reminders: ${reminders?'on':'off'}.`;
  result.hidden=false;
});

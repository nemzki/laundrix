/* Customer directory: original server queries and approved Admin-only customer writes. */
(function () {
  "use strict";
  var root=document.querySelector("[data-customer-directory]");
  if(!root || !window.fetch || !window.AbortController) return;
  document.documentElement.classList.add("customers-enhanced");
  // Delegate tooltips so server-paginated rows retain hover and keyboard hints.
  new bootstrap.Tooltip(root,{selector:"[data-edit-customer]",trigger:"hover focus",container:"body",customClass:"cm-edit-tooltip"});
  function hideEditHints(dispose) {root.querySelectorAll("[data-edit-customer]").forEach(function(button){var hint=bootstrap.Tooltip.getInstance(button);if(hint){if(dispose) hint.dispose();else hint.hide();}});}
  document.addEventListener("keydown",function(event){if(event.key==="Escape") hideEditHints(false);});
  var search=root.querySelector("[name=q]"), filter=root.querySelector("[name=filter]");
  var sheet=document.getElementById("customerSheet"), sheetUI=bootstrap.Offcanvas.getOrCreateInstance(sheet);
  var modal=document.getElementById("customerModal"), modalUI=bootstrap.Modal.getOrCreateInstance(modal);
  var form=document.getElementById("customerForm"), submit=form.querySelector("[type=submit]");
  var name=form.elements.full_name, contact=form.elements.contact_number, duplicate=form.elements.confirm_duplicate;
  var directoryController, profileController, editController, debounce, lastURL=new URL(location.href);
  var selected=null, profileURL=null, viewTrigger=null, editTrigger=null, returnSheet=false, saving=false, mode="add", editId=null, modalReady=false, formReady=false;
  var toast=document.querySelector("[data-customer-toast]");
  function announce(title,message) {
    toast.querySelector("[data-customer-toast-title]").textContent=title;
    toast.querySelector("[data-customer-toast-message]").textContent=message;toast.hidden=false;
  }
  toast.querySelector("[data-customer-toast-close]").addEventListener("click",function(){toast.hidden=true;});
  function safeURL(value) {var url=new URL(value,location.origin);if(url.origin!==location.origin) throw new Error("Invalid customer link.");return url;}
  async function readJSON(url,options) {
    var response=await fetch(url,Object.assign({credentials:"same-origin",cache:"no-store"},options));
    if(response.redirected) throw new Error("Please sign in again before continuing.");
    var data;
    try {data=await response.json();} catch {throw new Error("The request could not be confirmed. Refresh the directory before retrying.");}
    return {response:response,data:data};
  }
  function queryURL() {
    var url=new URL(root.dataset.indexUrl,location.origin);
    if(search.value.trim()) url.searchParams.set("q",search.value.trim());
    if(filter.value!=="all") url.searchParams.set("filter",filter.value);
    return url;
  }
  async function loadDirectory(url,push,clamped) {
    lastURL=new URL(url);clearTimeout(debounce);
    if(directoryController) directoryController.abort();
    var current=new AbortController();directoryController=current;
    var timer=setTimeout(function(){current.abort();},12000);
    root.dataset.state="loading";root.setAttribute("aria-busy","true");
    root.querySelector("[data-customer-load-error]").hidden=true;
    try {
      var response=await fetch(url,{credentials:"same-origin",cache:"no-store",signal:current.signal});
      if(!response.ok || response.redirected) throw new Error("Customers unavailable");
      var doc=new DOMParser().parseFromString(await response.text(),"text/html"), results=doc.querySelector("[data-customer-results]");
      if(!results) throw new Error("Customers unavailable");
      if(directoryController!==current) return;
      if(!clamped && Number(results.dataset.page)>Math.max(1,Number(results.dataset.pages))) {
        var bounded=new URL(url);if(Number(results.dataset.pages)>1) bounded.searchParams.set("page",results.dataset.pages);else bounded.searchParams.delete("page");
        return loadDirectory(bounded,push,true);
      }
      hideEditHints(true);
      root.querySelector("[data-customer-results]").replaceWith(results);
      document.querySelector("[data-directory-count]").textContent=doc.querySelector("[data-directory-count]").textContent;
      if(!push || document.activeElement!==search) search.value=url.searchParams.get("q") || "";
      filter.value=doc.querySelector("#customer-filter").value;
      root.querySelector("[data-customer-page]").hidden=!search.value.trim() && filter.value==="all";
      root.dataset.state="ready";root.querySelector("[data-customer-announcement]").textContent=results.dataset.total+" matching customers loaded.";
      if(push) history.pushState(null,"",url);else if(clamped) history.replaceState(null,"",url);
      return true;
    } catch {if(directoryController===current){root.dataset.state="error";root.querySelector("[data-customer-load-error]").hidden=false;}return false;}
    finally {clearTimeout(timer);if(directoryController===current) root.removeAttribute("aria-busy");}
  }
  root.querySelector(".cm-filters").addEventListener("submit",function(event){event.preventDefault();loadDirectory(queryURL(),true);});
  search.addEventListener("input",function(){clearTimeout(debounce);debounce=setTimeout(function(){loadDirectory(queryURL(),true);},300);});
  filter.addEventListener("change",function(){loadDirectory(queryURL(),true);});
  window.addEventListener("popstate",function(){loadDirectory(new URL(location.href),false);});
  function showSheetStatus(message,retry) {
    var container=sheet.querySelector("[data-customer-sheet-content]");container.replaceChildren();
    var profile=document.createElement("div");profile.className="cm-profile";
    var header=document.createElement("header");header.className="cm-profile-header";
    var heading=document.createElement("h2");heading.id="customerSheetTitle";heading.textContent="Customer Details";
    var close=document.createElement("button");close.className="btn-close";close.type="button";close.dataset.bsDismiss="offcanvas";close.setAttribute("aria-label","Close customer details");
    header.append(heading,close);
    var body=document.createElement("div");body.className="cm-profile-body";body.setAttribute("role","status");body.textContent=message;
    if(retry){var button=document.createElement("button");button.className="btn btn-outline";button.type="button";button.textContent="Retry";button.addEventListener("click",retry);body.appendChild(button);}
    profile.append(header,body);container.appendChild(profile);sheet.querySelector("[data-sheet-edit]").disabled=true;
  }
  function showProfile(customer) {
    var doc=new DOMParser().parseFromString(customer.profile_html,"text/html"), profile=doc.querySelector("[data-customer-profile]");
    if(!profile || Number(profile.dataset.customerProfile)!==customer.id) throw new Error("The selected customer could not be verified.");
    selected=customer;profileURL=safeURL(customer.url);
    sheet.querySelector("[data-customer-sheet-content]").replaceChildren(profile);
    sheet.querySelector("[data-sheet-edit]").disabled=false;
  }
  async function loadProfile(url,id) {
    if(profileController) profileController.abort();
    var current=new AbortController();profileController=current;
    var timer=setTimeout(function(){current.abort();},12000);
    showSheetStatus("Loading latest customer details...");
    try {
      var result=await readJSON(url,{signal:current.signal});
      if(profileController!==current) return;
      if(!result.response.ok || !result.data.ok || result.data.customer.id!==id) throw new Error("The selected customer could not be loaded.");
      showProfile(result.data.customer);
    } catch(error){if(profileController===current) showSheetStatus(error.message || "Customer details could not be loaded.",function(){loadProfile(url,id);});}
    finally {clearTimeout(timer);}
  }
  function clearErrors() {
    form.querySelector("[data-customer-errors]").hidden=true;
    form.querySelectorAll("[data-customer-error]").forEach(function(item){item.hidden=true;item.textContent="";});
    [name,contact].forEach(function(input){input.removeAttribute("aria-invalid");input.removeAttribute("aria-describedby");});
  }
  function enableFields(value) {name.disabled=!value;contact.disabled=!value;duplicate.disabled=!value;submit.disabled=!value;}
  async function prepareEdit(url,id) {
    if(editController) editController.abort();
    var current=new AbortController();editController=current;
    var timer=setTimeout(function(){current.abort();},12000);
    formReady=false;enableFields(false);
    try {
      var result=await readJSON(url,{signal:current.signal});
      if(editController!==current) return;
      if(!result.response.ok || !result.data.ok || result.data.customer.id!==id) throw new Error("Customer details could not be loaded.");
      var customer=result.data.customer;name.value=customer.full_name;contact.value=customer.contact_number;formReady=true;
      if(modalReady){enableFields(true);name.focus();}
    } catch(error) {
      if(editController!==current) return;
      var box=form.querySelector("[data-customer-errors]");box.hidden=false;box.textContent=error.message || "Customer details could not be loaded.";
      var retry=document.createElement("button");retry.type="button";retry.className="btn btn-outline";retry.textContent="Retry";retry.addEventListener("click",function(){clearErrors();prepareEdit(url,id);});box.appendChild(retry);
    } finally {clearTimeout(timer);}
  }
  function openEditor(kind,url,id,fromSheet,trigger) {
    function start() {
      mode=kind;editId=id;returnSheet=fromSheet;editTrigger=trigger;form.reset();clearErrors();toast.hidden=true;
      duplicate.required=false;form.querySelector("[data-customer-duplicate]").hidden=true;
      form.querySelector("[data-duplicate-confirm-label]").textContent=kind==="edit" ? "Use this contact number despite the existing customer match." : "Save a separate customer with this contact number.";
      form.action=safeURL(url);modal.querySelector("#customerModalTitle").textContent=kind==="edit" ? "Edit Customer" : "Add Customer";
      modal.querySelector("[data-customer-modal-description]").textContent=kind==="edit" ? "Update this customer's contact details." : "Enter the customer's contact details.";
      submit.textContent=kind==="edit" ? "Save Changes" : "Save Customer";modalReady=false;formReady=kind==="add";enableFields(false);modalUI.show();
      if(kind==="edit") prepareEdit(url,id);
    }
    if(fromSheet && sheet.classList.contains("show")){sheet.addEventListener("hidden.bs.offcanvas",start,{once:true});sheetUI.hide();}
    else start();
  }
  root.addEventListener("click",function(event){
    if(event.target.closest("[data-customer-retry]")){loadDirectory(lastURL,lastURL.href!==location.href);return;}
    var pageLink=event.target.closest(".cm-pagination a, [data-customer-page]");
    if(pageLink && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button===0){event.preventDefault();loadDirectory(new URL(pageLink.href),true);return;}
    var action=event.target.closest("[data-view-customer], [data-edit-customer]");
    if(!action) return;
    hideEditHints(false);
    var row=action.closest("[data-customer-id]"), id=Number(row.dataset.customerId), url=safeURL(row.dataset.customerUrl);
    if(action.hasAttribute("data-view-customer")){viewTrigger=action;selected=null;showSheetStatus("Loading latest customer details...");sheetUI.show();loadProfile(url,id);}
    else openEditor("edit",url,id,false,action);
  });
  document.querySelector("[data-add-customer]").addEventListener("click",function(event){if(event.ctrlKey || event.metaKey || event.shiftKey) return;event.preventDefault();openEditor("add",root.dataset.createUrl,null,false,event.currentTarget);});
  sheet.querySelector("[data-sheet-edit]").addEventListener("click",function(){if(selected) openEditor("edit",profileURL,selected.id,true,null);});
  sheet.addEventListener("hidden.bs.offcanvas",function(){if(profileController) profileController.abort();profileController=null;if(viewTrigger?.isConnected) viewTrigger.focus();});
  // Enable editing after Bootstrap finishes its focus transition, so typing cannot
  // be redirected to the name field while the modal is still opening.
  modal.addEventListener("shown.bs.modal",function(){modalReady=true;if(formReady){enableFields(true);name.focus();}});
  modal.addEventListener("hide.bs.modal",function(event){if(saving) event.preventDefault();else modalReady=false;});
  modal.addEventListener("hidden.bs.modal",function(){
    if(editController) editController.abort();editController=null;
    if(returnSheet && selected){returnSheet=false;showProfile(selected);sheetUI.show();}
    else if(editTrigger?.isConnected) editTrigger.focus();
  });
  form.addEventListener("input",function(event){if(event.target!==duplicate){duplicate.checked=false;duplicate.required=false;form.querySelector("[data-customer-duplicate]").hidden=true;}});
  form.addEventListener("submit",async function(event){
    event.preventDefault();if(saving || !form.reportValidity()) return;
    var payload={full_name:name.value,contact_number:contact.value,confirm_duplicate:duplicate.checked};
    saving=true;enableFields(false);submit.textContent="Saving...";clearErrors();
    try {
      var result=await readJSON(form.action,{method:"POST",headers:{"Content-Type":"application/json","X-CSRFToken":form.elements.csrf_token.value},body:JSON.stringify(payload)});
      if(!result.response.ok || !result.data.ok){
        var errors=result.data.errors || {customer:["The customer could not be saved."]};
        var box=form.querySelector("[data-customer-errors]");box.textContent=Object.values(errors).flat().join(" ");box.hidden=false;
        [["customer_name",name],["customer_contact",contact]].forEach(function(pair){if(errors[pair[0]]){var area=form.querySelector('[data-customer-error="'+pair[0]+'"]');area.textContent=errors[pair[0]].join(" ");area.hidden=false;pair[1].setAttribute("aria-invalid","true");pair[1].setAttribute("aria-describedby",area.id);}});
        if(result.data.duplicates?.length){form.querySelector("[data-customer-duplicates]").textContent=result.data.duplicates.map(function(c){return c.full_name+" — "+c.contact_number;}).join("; ");form.querySelector("[data-customer-duplicate]").hidden=false;duplicate.required=true;}
        return;
      }
      var saved=result.data.customer;
      if(!saved || (mode==="edit" && saved.id!==editId)) throw new Error("Customer save could not be verified. Refresh the directory.");
      selected=saved;profileURL=safeURL(saved.url);if(mode==="add") returnSheet=true;
      saving=false;modalUI.hide();
      announce(mode==="edit" ? "Customer updated" : "Customer added",saved.full_name+" was saved successfully.");
      var refreshed=await loadDirectory(new URL(location.href),false);
      if(!refreshed) announce("Customer saved",saved.full_name+" was saved. Retry loading the directory to refresh the list.");
    } catch(error){var area=form.querySelector("[data-customer-errors]");area.textContent=error.message || "The save could not be confirmed. Refresh before retrying.";area.hidden=false;}
    finally {saving=false;enableFields(modalReady && formReady);submit.textContent=mode==="edit" ? "Save Changes" : "Save Customer";}
  });
  document.addEventListener("visibilitychange",function(){if(!document.hidden){loadDirectory(new URL(location.href),false);if(sheet.classList.contains("show") && selected) loadProfile(profileURL,selected.id);}});
  root.dataset.state="ready";
})();

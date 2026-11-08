/* Original server-rendered balances; shared payment form, fresh server refetches. */
(function () {
  "use strict";
  var root = document.querySelector("[data-outstanding]");
  if (!root || !window.fetch) return;
  var form = root.querySelector(".ob-filters");
  var modal = document.getElementById("recordPaymentModal");
  var dialog = bootstrap.Modal.getOrCreateInstance(modal);
  var controller, modalController, trigger, selectedURL, selectedRef, lastURL = new URL(location.href);
  var initialContent = modal.querySelector(".modal-content").cloneNode(true);
  var toast = document.querySelector("[data-ob-toast]");
  function notify(title, message, success) {
    toast.querySelector("[data-toast-title]").textContent = title;
    toast.querySelector("[data-toast-message]").textContent = message;
    toast.classList.toggle("is-success", Boolean(success)); toast.hidden = false;
  }
  toast.querySelector("[data-toast-close]").addEventListener("click", function () { toast.hidden = true; });
  async function documentAt(url, signal) {
    var response = await fetch(url, { credentials:"same-origin", cache:"no-store", signal:signal });
    if (!response.ok || response.redirected) throw new Error("The requested information could not be loaded.");
    return new DOMParser().parseFromString(await response.text(), "text/html");
  }
  var countVersion = 0;
  var records = [], perPage = 15, complete = false, scope = "", debounce;
  var selects = [];
  function enhanceSelect(select) {
    var wrapper = select.closest(".ob-select-wrap");
    var trigger = document.createElement("button");
    trigger.type="button"; trigger.className="btn btn-outline ob-select-trigger";
    trigger.dataset.bsToggle="dropdown"; trigger.setAttribute("aria-haspopup","listbox"); trigger.setAttribute("aria-expanded","false");
    trigger.setAttribute("aria-label",select.getAttribute("aria-label"));
    var label=document.createElement("span"); trigger.appendChild(label);
    var arrow=document.createElementNS("http://www.w3.org/2000/svg","svg");
    arrow.setAttribute("viewBox","0 0 24 24"); arrow.setAttribute("width","16"); arrow.setAttribute("height","16"); arrow.setAttribute("fill","none"); arrow.setAttribute("stroke","currentColor"); arrow.setAttribute("stroke-width","1.75"); arrow.setAttribute("aria-hidden","true");
    var path=document.createElementNS(arrow.namespaceURI,"path"); path.setAttribute("d","m6 9 6 6 6-6"); arrow.appendChild(path); trigger.appendChild(arrow);
    var menu=document.createElement("div"); menu.className="dropdown-menu ob-select-menu"; menu.setAttribute("role","listbox"); menu.setAttribute("aria-label",select.getAttribute("aria-label"));
    Array.from(select.options).forEach(function (option) {
      var item=document.createElement("button"); item.type="button"; item.className="dropdown-item"; item.setAttribute("role","option"); item.dataset.value=option.value;
      var text=document.createElement("span"); text.textContent=option.textContent; item.appendChild(text);
      var check=document.createElement("span"); check.className="ob-option-check"; check.textContent="\u2713"; check.setAttribute("aria-hidden","true"); item.appendChild(check);
      item.addEventListener("click",function () { select.value=option.value; select.dispatchEvent(new Event("change",{bubbles:true})); bootstrap.Dropdown.getOrCreateInstance(trigger).hide(); trigger.focus(); });
      menu.appendChild(item);
    });
    wrapper.classList.add("dropdown"); select.classList.add("visually-hidden"); select.tabIndex=-1; select.setAttribute("aria-hidden","true");
    wrapper.appendChild(trigger); wrapper.appendChild(menu);
    bootstrap.Dropdown.getOrCreateInstance(trigger,{ popperConfig:function (config) { return Object.assign({},config,{strategy:"fixed"}); } });
    var control={ select:select, trigger:trigger, sync:function () {
      label.textContent=select.selectedOptions[0]?.textContent || "";
      trigger.setAttribute("aria-label",select.getAttribute("aria-label")+": "+label.textContent);
      menu.querySelectorAll("[role=option]").forEach(function (item) { var active=item.dataset.value===select.value; item.classList.toggle("active",active); item.setAttribute("aria-selected",String(active)); });
    } };
    control.sync(); selects.push(control);
  }
  form.querySelectorAll("select").forEach(enhanceSelect);
  function disableControls(value) {
    form.querySelectorAll("input,select").forEach(function (field) { field.disabled=value; });
    selects.forEach(function (control) { control.trigger.disabled=value; });
  }
  function stateAt(url) {
    var status=url.searchParams.get("status") || "outstanding";
    if (!["outstanding","unpaid","partial","paid"].includes(status)) status="outstanding";
    var sort=url.searchParams.get("sort") || "highest";
    if (!["highest","lowest","oldest","newest"].includes(sort)) sort="highest";
    return { status:status, sort:sort, q:(url.searchParams.get("q") || "").trim(), page:Math.max(1,Number.parseInt(url.searchParams.get("page"),10) || 1) };
  }
  async function counts() {
    var version = ++countVersion;
    root.querySelector("[data-count-error]").hidden = true;
    try {
      var values = await Promise.all([root.dataset.countUnpaid, root.dataset.countPartial].map(async function (url) {
        var doc = await documentAt(url, AbortSignal.timeout(12000));
        var result = doc.querySelector("[data-orders-results]");
        if (!result || !/^\d+$/.test(result.dataset.total)) throw new Error("Counts unavailable");
        return Number(result.dataset.total);
      }));
      if (version !== countVersion) return;
      root.querySelector("[data-unpaid-count]").textContent = values[0];
      root.querySelector("[data-partial-count]").textContent = values[1];
    } catch {
      if (version !== countVersion) return;
      root.querySelector("[data-unpaid-count]").textContent = "\u2014";
      root.querySelector("[data-partial-count]").textContent = "\u2014";
      root.querySelector("[data-count-error]").hidden = false;
    }
  }
  function moneyCents(value) {
    var match=/^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value || "");
    if (!match) throw new Error("Invalid saved balance");
    var amount=(Number(match[2])*100+Number((match[3] || "").padEnd(2,"0")))*(match[1] ? -1 : 1);
    if (!Number.isSafeInteger(amount)) throw new Error("Invalid saved balance");
    return amount;
  }
  function recordFrom(row) {
    var created=Date.parse(row.dataset.created+"Z"), id=Number(row.dataset.orderId);
    var status=row.querySelector("[data-payment-status]")?.dataset.paymentStatus;
    if (!Number.isFinite(created) || !Number.isSafeInteger(id) || !["unpaid","partial","paid"].includes(status)) throw new Error("Invalid order data");
    return { row:row, ref:row.dataset.orderRef, id:id, created:created, createdKey:row.dataset.created, balance:moneyCents(row.dataset.balance), payment:status,
      name:row.querySelector(".ob-customer strong").textContent.toLocaleLowerCase(),
      contact:row.querySelector(".ob-contact").textContent.replace(/\D/g,"") };
  }
  function render(url,push) {
    if (!complete) return;
    var state=stateAt(url), query=state.q.toLocaleLowerCase(), digits=state.q.replace(/\D/g,"");
    var matching=records.filter(function (record) {
      return (state.status==="outstanding" || state.status===record.payment) &&
        (!query || record.ref.toLocaleLowerCase().includes(query) || record.name.includes(query) || (digits.length>=3 && record.contact.includes(digits)));
    });
    matching.sort(function (a,b) {
      if (state.sort==="highest" || state.sort==="lowest") {
        var amount=(state.sort==="highest" ? b.balance-a.balance : a.balance-b.balance);
        if (amount) return amount;
      }
      var chronology=a.createdKey<b.createdKey ? -1 : a.createdKey>b.createdKey ? 1 : 0;
      return state.sort==="oldest" ? chronology || a.id-b.id : -chronology || b.id-a.id;
    });
    var pages=Math.ceil(matching.length/perPage), page=Math.min(state.page,Math.max(1,pages));
    var tbody=root.querySelector(".ob-rows"); tbody.replaceChildren();
    matching.slice((page-1)*perPage,page*perPage).forEach(function (record) { tbody.appendChild(record.row.cloneNode(true)); });
    if (!matching.length) {
      var tr=document.createElement("tr"), td=document.createElement("td"), title=document.createElement("strong"), hint=document.createElement("p");
      td.colSpan=8; td.className="ob-empty";
      title.textContent=state.q ? "No orders match your filters." : (state.status==="paid" ? "No fully paid orders." : "No orders owe a balance.");
      hint.textContent="Try another search or clear your filters."; td.append(title,hint); tr.appendChild(td); tbody.appendChild(tr);
    }
    var results=root.querySelector("[data-ob-results]"); results.dataset.total=String(matching.length); results.dataset.page=String(page); results.dataset.pages=String(pages);
    var footer=root.querySelector(".ob-footer"); footer.replaceChildren();
    var summary=document.createElement("span"); summary.textContent="Showing "+(matching.length ? (page-1)*perPage+1 : 0)+"\u2013"+Math.min(page*perPage,matching.length)+" of "+matching.length+" orders";
    footer.appendChild(summary);
    var pager=document.createElement("nav"); pager.className="pagination"; pager.setAttribute("aria-label","Pagination");
    function pageItem(label,target,disabled,active) {
      var item=document.createElement(disabled ? "button" : "a"); item.className="btn btn-outline btn-sm"; item.textContent=label;
      if (disabled) item.disabled=true;
      else { var next=new URL(url); if (target===1) next.searchParams.delete("page"); else next.searchParams.set("page",target); item.href=next.href; }
      if (active) item.setAttribute("aria-current","page"); pager.appendChild(item);
    }
    pageItem("Previous",page-1,page===1,false);
    var numbers=new Set([1,pages,page-1,page,page+1]); var previous=0;
    Array.from(numbers).filter(function (n) {return n>=1 && n<=pages;}).sort(function(a,b){return a-b;}).forEach(function(n) {
      if(previous && n>previous+1) {var gap=document.createElement("span"); gap.textContent="\u2026"; pager.appendChild(gap);}
      pageItem(String(n),n,false,n===page);previous=n;
    });
    pageItem("Next",page+1,page>=pages,false); footer.appendChild(pager);
    var search=form.querySelector("[name=q]"); if (!push || document.activeElement!==search || search.value.trim()!==state.q) search.value=state.q;
    var payment=form.querySelector("[name=status]"); if(payment) payment.value=state.status;
    form.querySelector("[name=sort]").value=state.sort; selects.forEach(function(control){control.sync();});
    form.querySelector("[data-ob-link]").hidden=!state.q && state.status==="outstanding" && state.sort==="highest";
    root.dataset.state="ready"; root.querySelector("[data-ob-announcement]").textContent=matching.length+" matching orders loaded.";
    var canonical=new URL(url); if(page===1) canonical.searchParams.delete("page"); else canonical.searchParams.set("page",page);
    lastURL=canonical;
    if(push) history.pushState(null,"",canonical);
    else if(canonical.href!==location.href) history.replaceState(null,"",canonical);
  }
  async function load(url,push) {
    lastURL=new URL(url); clearTimeout(debounce);
    if(controller) controller.abort();
    var current=new AbortController(); controller=current;
    var timeout=setTimeout(function(){current.abort();},20000);
    complete=false; disableControls(true); root.dataset.state="loading"; root.setAttribute("aria-busy","true");
    try {
      // Existing endpoint is paginated. Collect the ENTIRE authorized scope before
      // enabling frontend search/sort/pagination; never filter only visible rows.
      var source=new URL(form.action); var nextScope=stateAt(url).status==="paid" ? "paid" : "outstanding";
      source.searchParams.set("status",nextScope);
      var first=await documentAt(source,current.signal), firstResults=first.querySelector("[data-ob-results]");
      if(!firstResults) throw new Error("Balances unavailable");
      var total=Number(firstResults.dataset.total), pages=Number(firstResults.dataset.pages), size=Number(firstResults.dataset.perPage);
      if(!Number.isSafeInteger(total) || total<0 || !Number.isSafeInteger(size) || size<=0 || pages!==Math.ceil(total/size)) throw new Error("Incomplete result metadata");
      var docs=[first];
      for(var start=2;start<=pages;start+=3) {
        var requests=[];
        for(var p=start;p<=Math.min(start+2,pages);p++) {var pageURL=new URL(source);pageURL.searchParams.set("page",p);requests.push(documentAt(pageURL,current.signal));}
        var batch=await Promise.all(requests); docs.push.apply(docs,batch);
      }
      if(controller!==current) return;
      var collected=[];
      docs.forEach(function(doc,index){
        var data=doc.querySelector("[data-ob-results]");
        if(!data || Number(data.dataset.total)!==total || Number(data.dataset.page)!==index+1) throw new Error("Balances changed during loading");
        Array.from(data.querySelectorAll(".ob-rows tr[data-order-ref]")).forEach(function(row){collected.push(recordFrom(row));});
      });
      if(collected.length!==total || new Set(collected.map(function(r){return r.ref;})).size!==total) throw new Error("Incomplete balances; retry to refresh");
      records=collected;perPage=size;scope=nextScope;
      root.querySelector("[data-ob-results]").replaceWith(firstResults);
      ["[data-owing-total]","[data-owing-count]"].forEach(function(selector){root.querySelector(selector).textContent=first.querySelector(selector).textContent;});
      complete=true;disableControls(false);render(url,push);
    } catch {if(controller===current) {current.abort();root.dataset.state="error";}}
    finally {clearTimeout(timeout);if(controller===current) root.removeAttribute("aria-busy");}
  }
  function filterURL() {
    var url=new URL(form.action);
    var status=form.querySelector("[name=status]").value;
    if(status!=="outstanding") url.searchParams.set("status",status);
    var query=form.querySelector("[name=q]").value.trim();if(query) url.searchParams.set("q",query);
    var sort=form.querySelector("[name=sort]").value;if(sort!=="highest") url.searchParams.set("sort",sort);
    return url;
  }
  function apply(url,push) {
    clearTimeout(debounce);
    if(!complete || (stateAt(url).status==="paid" ? "paid" : "outstanding")!==scope) load(url,push);
    else render(url,push);
  }
  root.addEventListener("input",function(event){if(event.target.matches("#ob-search")){clearTimeout(debounce);debounce=setTimeout(function(){apply(filterURL(),true);},250);}});
  root.addEventListener("change",function(event){if(event.target.matches(".ob-filters select")) apply(filterURL(),true);});
  root.addEventListener("submit",function(event){if(event.target.matches(".ob-filters")){event.preventDefault();apply(filterURL(),true);}});
  root.addEventListener("click",function(event){
    if(event.target.closest("[data-count-retry]")){counts();return;}
    if(event.target.closest("[data-ob-retry]")){load(lastURL,false);return;}
    var link=event.target.closest(".pagination a, [data-ob-link]");
    if(link && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button===0){event.preventDefault();apply(new URL(link.href),true);return;}
    var payment=event.target.closest("[data-ob-payment]");
    if(payment && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button===0){
      event.preventDefault();trigger=payment;selectedURL=new URL(payment.href);selectedURL.hash="";
      selectedRef=payment.closest("[data-order-ref]").dataset.orderRef;
      modal.querySelector(".modal-content").replaceWith(initialContent.cloneNode(true));delete modal.dataset.paymentMounted;
      dialog.show();openPayment();
    }
  });
  async function openPayment() {
    if (modalController) modalController.abort();
    var current = new AbortController(); modalController = current;
    var timeout = setTimeout(function () { current.abort(); },12000);
    try {
      var doc = await documentAt(selectedURL,current.signal);
      var order = doc.querySelector(".order-detail"), content = doc.querySelector("#recordPaymentModal .modal-content");
      if (!order || order.dataset.ref !== selectedRef) throw new Error("The selected order could not be verified.");
      if (!content) throw new Error(Number(order.dataset.balance) <= 0 ? "This order has no remaining balance. Refresh the list." : "Payment recording is unavailable for this order. Open Order Details.");
      if (modalController !== current) return;
      modal.querySelector(".modal-content").replaceWith(content);
      window.LaundrixPayments.mount(modal, { balance:order.dataset.balance, reference:selectedRef, notify:notify,
        onSuccess:async function (saved, message) {
          dialog.hide(); notify("Payment recorded",message,true);
          await load(new URL(location.href),false); await counts();
          if (root.dataset.state === "error") notify("Payment recorded",message + " Refresh the list to see the updated balances.",true);
        }
      });
      modal.focus({preventScroll:true});
    } catch (error) {
      if (modalController !== current) return;
      var area = modal.querySelector("[data-ob-modal-status]");
      if (!area) return;
      area.textContent = error.message || "Order details could not be loaded.";
      area.classList.add("ob-modal-error");
      var retry = document.createElement("button"); retry.type="button"; retry.className="btn btn-outline"; retry.textContent="Retry";
      retry.addEventListener("click",function () { area.textContent="Loading latest order details..."; openPayment(); }); area.appendChild(retry);
    } finally { clearTimeout(timeout); }
  }
  modal.addEventListener("hidden.bs.modal",function () { if (modalController) modalController.abort(); modalController=null; if (modal.paymentDispose) modal.paymentDispose(); if (trigger && trigger.isConnected) trigger.focus({preventScroll:true}); });
  window.addEventListener("popstate",function () { apply(new URL(location.href),false); });
  document.addEventListener("visibilitychange",function () { if (!document.hidden) { load(new URL(location.href),false); counts(); } });
  load(new URL(location.href),false); counts();
})();

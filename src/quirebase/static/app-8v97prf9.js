function v(q){let f=q.split(/([A-Z])/g),k=[],h="",b;for(b=1;b<f.length;b+=2)h=h.slice(0,f[b].charCodeAt(0)-65)+f[b+1],k.push(h);return k}
export{v as a};

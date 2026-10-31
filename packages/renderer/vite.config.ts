import {defineConfig} from 'vite';
// Classic IIFE avoids file:// ES-module origin restrictions in WKWebView.
export default defineConfig({base:'./',plugins:[{name:'offline-classic-entry',transformIndexHtml:{order:'post',handler:html=>html.replace(/type="module" crossorigin/g,'defer').replace(/ crossorigin/g,'')}}],build:{target:'es2022',modulePreload:false,chunkSizeWarningLimit:900,rollupOptions:{output:{format:'iife',entryFileNames:'assets/renderer.js',inlineDynamicImports:true}}}});

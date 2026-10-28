// Lets TypeScript import .vue files; vue-tsc checks their contents.
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

export function formatSeconds(seconds:number|null|undefined):string{
  if(seconds==null || Number.isNaN(seconds)) return '0s'
  if(seconds<60) return `${Math.round(seconds)}s`
  return `${Math.floor(seconds/60)}m ${Math.round(seconds%60)}s`
}

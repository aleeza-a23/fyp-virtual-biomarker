import { useEffect, useRef } from 'react'
import OpenSeadragon from 'openseadragon'
import api, { API } from '../api'

export default function SlideViewer({ slideId }) {
  const el = useRef(null)
  useEffect(() => {
    let viewer
    api.get(`/slides/${slideId}/info`).then(({ data }) => {
      viewer = OpenSeadragon({
        element: el.current,
        showNavigator: true,
        prefixUrl: 'https://cdn.jsdelivr.net/npm/openseadragon@4/build/openseadragon/images/',
        loadTilesWithAjax: true,
        ajaxHeaders: { Authorization: `Bearer ${sessionStorage.getItem('token')}` },
        tileSources: {
          width: data.width, height: data.height, tileSize: data.tile,
          minLevel: 0, maxLevel: data.max_level,
          getTileUrl: (l, x, y) => `${API}/slides/${slideId}/tile/${l}/${x}/${y}`,
        },
      })
    })
    return () => viewer && viewer.destroy()
  }, [slideId])
  return <div ref={el} style={{ height: 520 }} className="rounded border bg-slate-100" />
}
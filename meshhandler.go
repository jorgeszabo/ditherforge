//go:build amd64 || arm64 || 386 || arm

package main

import (
	"fmt"
	"net/http"
	"strings"
	"sync"

	"github.com/rtwfroody/ditherforge/internal/meshpreview"
	"github.com/rtwfroody/ditherforge/internal/pipeline"
)

// meshHandler serves mesh data as binary over HTTP. Mesh data is stored
// in memory and served at /mesh/{id}. The binary format is:
//
//	Header (20 bytes):
//	  uint32 nVertices  (number of float32 values, i.e. vertex count * 3)
//	  uint32 nFaces     (number of uint32 values, i.e. face count * 3)
//	  uint32 nColors    (number of uint16 values, i.e. face count * 3)
//	  uint32 nUVs       (number of float32 values, i.e. vertex count * 2; 0 if absent)
//	  uint32 nTexIdx    (number of int32 values, i.e. face count; 0 if absent)
//	Body:
//	  float32[nVertices]
//	  uint32[nFaces]
//	  uint16[nColors]
//	  float32[nUVs]       (omitted if nUVs == 0)
//	  int32[nTexIdx]      (omitted if nTexIdx == 0)
//	Textures:
//	  uint32 nTextures
//	  For each texture:
//	    uint32 length
//	    []byte base64-encoded JPEG data
//	Sticker overlay:
//	  uint32 hasStickerData  (0 or 1)
//	  If 1:
//	    uint32 nStickerUVs
//	    float32[nStickerUVs]   (per face-vertex sticker UVs)
//	    uint32 nStickerMask
//	    uint8[nStickerMask]    (per-face sticker mask)
//	    uint32 nStickerBounds
//	    float32[nStickerBounds] (per-face [minU,maxU,minV,maxV] atlas clamp bounds)
//	    uint32 atlasLen
//	    []byte base64-encoded PNG atlas
//	MaterialX preview atlas (optional, appended after sticker section):
//	  uint32 hasBaseColorAtlas  (0 or 1)
//	  If 1:
//	    uint32 width
//	    uint32 height
//	    uint32 nUVs                  (= nFaces*6, [u,v] per face-vertex)
//	    float32[nUVs]                normalized [0,1]
//	    uint32 imageLen
//	    []byte base64-encoded PNG    (with "png:" prefix)
//	Face alpha (optional, appended after MaterialX section):
//	  uint32 hasFaceAlpha          (0 or 1)
//	  If 1:
//	    uint32 nFaceAlpha          (= face count, one byte per face, 0..255)
//	    uint8[nFaceAlpha]
//	Face render class (optional, appended after face alpha):
//	  uint32 hasFaceRenderClass    (0 or 1)
//	  If 1:
//	    uint32 nFaceRenderClass    (= face count, one byte per face, 0..2)
//	    uint8[nFaceRenderClass]    (0=opaque, 1=cutout, 2=blend)
//	Sim face colors (optional, appended after face render class):
//	  uint32 hasSimColors          (0 or 1)
//	  If 1:
//	    uint32 nSimColors          (= face count * 3, uint16 [r,g,b] per face)
//	    uint16[nSimColors]         (per-cell print-simulation colors, 0..255)
type meshHandler struct {
	mu     sync.RWMutex
	meshes map[string]*pipeline.MeshData
	nextID int
}

func newMeshHandler() *meshHandler {
	return &meshHandler{meshes: make(map[string]*pipeline.MeshData)}
}

// Store saves mesh data and returns an ID that can be used to fetch it.
func (h *meshHandler) Store(mesh *pipeline.MeshData) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.nextID++
	id := fmt.Sprintf("m%d", h.nextID)
	h.meshes[id] = mesh
	return id
}

// Remove deletes stored mesh data.
func (h *meshHandler) Remove(id string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.meshes, id)
}

func (h *meshHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Expect path like /mesh/m123
	path := strings.TrimPrefix(r.URL.Path, "/mesh/")
	if path == r.URL.Path {
		http.NotFound(w, r)
		return
	}

	// Hold the read lock for the entire response to prevent Remove() from
	// freeing mesh data while we're writing it out.
	h.mu.RLock()
	defer h.mu.RUnlock()
	mesh, ok := h.meshes[path]
	if !ok {
		http.NotFound(w, r)
		return
	}

	w.Header().Set("Content-Type", "application/octet-stream")

	_ = meshpreview.Write(w, mesh)
}

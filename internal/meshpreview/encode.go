// Package meshpreview encodes the binary mesh format shared by browser and desktop viewers.
package meshpreview

import (
	"encoding/binary"
	"github.com/rtwfroody/ditherforge/internal/pipeline"
	"io"
	"unsafe"
)

func float32SliceToBytes(s []float32) []byte {
	if len(s) == 0 {
		return nil
	}
	return unsafe.Slice((*byte)(unsafe.Pointer(&s[0])), len(s)*4)
}

func uint32SliceToBytes(s []uint32) []byte {
	if len(s) == 0 {
		return nil
	}
	return unsafe.Slice((*byte)(unsafe.Pointer(&s[0])), len(s)*4)
}

func uint16SliceToBytes(s []uint16) []byte {
	if len(s) == 0 {
		return nil
	}
	return unsafe.Slice((*byte)(unsafe.Pointer(&s[0])), len(s)*2)
}

func int32SliceToBytes(s []int32) []byte {
	if len(s) == 0 {
		return nil
	}
	return unsafe.Slice((*byte)(unsafe.Pointer(&s[0])), len(s)*4)
}

// Write streams a preview mesh using the existing desktop viewer format.
func Write(w io.Writer, mesh *pipeline.MeshData) error {
	var err error
	write := func(b []byte) {
		if err != nil {
			return
		}
		var n int
		n, err = w.Write(b)
		if err == nil && n != len(b) {
			err = io.ErrShortWrite
		}
	}
	nVerts := uint32(len(mesh.Vertices))
	nFaces := uint32(len(mesh.Faces))
	nColors := uint32(len(mesh.FaceColors))
	nUVs := uint32(len(mesh.UVs))
	nTexIdx := uint32(len(mesh.FaceTextureIdx))

	// Header.
	var hdr [20]byte
	binary.LittleEndian.PutUint32(hdr[0:], nVerts)
	binary.LittleEndian.PutUint32(hdr[4:], nFaces)
	binary.LittleEndian.PutUint32(hdr[8:], nColors)
	binary.LittleEndian.PutUint32(hdr[12:], nUVs)
	binary.LittleEndian.PutUint32(hdr[16:], nTexIdx)
	write(hdr[:])

	// Write typed slices as raw bytes (little-endian on LE platforms,
	// which covers all supported targets).
	write(float32SliceToBytes(mesh.Vertices))
	write(uint32SliceToBytes(mesh.Faces))
	write(uint16SliceToBytes(mesh.FaceColors))
	write(float32SliceToBytes(mesh.UVs))
	write(int32SliceToBytes(mesh.FaceTextureIdx))

	// Textures (base64 strings).
	nTex := uint32(0)
	if mesh.Textures != nil {
		nTex = uint32(len(mesh.Textures))
	}
	var tmp [4]byte
	binary.LittleEndian.PutUint32(tmp[:], nTex)
	write(tmp[:])
	for _, tex := range mesh.Textures {
		b := []byte(tex)
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(b)))
		write(tmp[:])
		write(b)
	}

	// Sticker overlay section.
	if len(mesh.StickerUVs) > 0 && mesh.StickerAtlas != "" {
		binary.LittleEndian.PutUint32(tmp[:], 1) // hasStickerData
		write(tmp[:])

		binary.LittleEndian.PutUint32(tmp[:], uint32(len(mesh.StickerUVs)))
		write(tmp[:])
		write(float32SliceToBytes(mesh.StickerUVs))

		binary.LittleEndian.PutUint32(tmp[:], uint32(len(mesh.StickerFaceMask)))
		write(tmp[:])
		write(mesh.StickerFaceMask)

		binary.LittleEndian.PutUint32(tmp[:], uint32(len(mesh.StickerBounds)))
		write(tmp[:])
		write(float32SliceToBytes(mesh.StickerBounds))

		atlasBytes := []byte(mesh.StickerAtlas)
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(atlasBytes)))
		write(tmp[:])
		write(atlasBytes)
	} else {
		binary.LittleEndian.PutUint32(tmp[:], 0) // no sticker data
		write(tmp[:])
	}

	// MaterialX preview atlas (optional). Image as base64 PNG/JPEG
	// (matches sticker atlas convention); per-face-vertex UVs
	// indexed alongside the unpacked face buffer the frontend builds.
	if atl := mesh.BaseColorAtlas; atl != nil && atl.Image != "" && len(atl.FaceVertexUVs) > 0 {
		binary.LittleEndian.PutUint32(tmp[:], 1) // hasBaseColorAtlas
		write(tmp[:])
		binary.LittleEndian.PutUint32(tmp[:], uint32(atl.Width))
		write(tmp[:])
		binary.LittleEndian.PutUint32(tmp[:], uint32(atl.Height))
		write(tmp[:])
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(atl.FaceVertexUVs)))
		write(tmp[:])
		write(float32SliceToBytes(atl.FaceVertexUVs))
		imgBytes := []byte(atl.Image)
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(imgBytes)))
		write(tmp[:])
		write(imgBytes)
	} else {
		binary.LittleEndian.PutUint32(tmp[:], 0) // no atlas
		write(tmp[:])
	}

	// Per-face alpha (optional). Carries continuous per-face alpha
	// for the input preview so the renderer can blend translucent
	// faces; texture alpha is handled per-pixel via the texture
	// itself.
	if len(mesh.FaceAlpha) > 0 {
		binary.LittleEndian.PutUint32(tmp[:], 1) // hasFaceAlpha
		write(tmp[:])
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(mesh.FaceAlpha)))
		write(tmp[:])
		write(mesh.FaceAlpha)
	} else {
		binary.LittleEndian.PutUint32(tmp[:], 0) // no per-face alpha
		write(tmp[:])
	}

	// Per-face render class (optional): 0 = opaque, 1 = cutout (alpha
	// test), 2 = blend. Lets the renderer draw each face per-fragment —
	// alpha-testing cutout faces (so they still write depth) and routing
	// only genuinely translucent faces to the depth-write-off blend pass.
	if len(mesh.FaceRenderClass) > 0 {
		binary.LittleEndian.PutUint32(tmp[:], 1) // hasFaceRenderClass
		write(tmp[:])
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(mesh.FaceRenderClass)))
		write(tmp[:])
		write(mesh.FaceRenderClass)
	} else {
		binary.LittleEndian.PutUint32(tmp[:], 0) // no render class
		write(tmp[:])
	}

	// Per-cell print-simulation colors (optional): flat uint16 [r,g,b] per
	// face, the neighbor-blended effective color for the print-sim preview.
	if len(mesh.SimFaceColors) > 0 {
		binary.LittleEndian.PutUint32(tmp[:], 1) // hasSimColors
		write(tmp[:])
		binary.LittleEndian.PutUint32(tmp[:], uint32(len(mesh.SimFaceColors)))
		write(tmp[:])
		write(uint16SliceToBytes(mesh.SimFaceColors))
	} else {
		binary.LittleEndian.PutUint32(tmp[:], 0) // no sim colors
		write(tmp[:])
	}
	return err
}

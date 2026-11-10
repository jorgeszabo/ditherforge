package meshpreview

import (
	"bytes"
	"encoding/binary"
	"errors"
	"testing"

	"github.com/rtwfroody/ditherforge/internal/pipeline"
)

func TestExistingViewerBinaryContract(t *testing.T) {
	mesh := &pipeline.MeshData{Vertices: []float32{0, 0, 0, 1, 0, 0, 0, 1, 0}, Faces: []uint32{0, 1, 2}, FaceColors: []uint16{255, 128, 0}}
	var b bytes.Buffer
	if err := Write(&b, mesh); err != nil {
		t.Fatal(err)
	}
	r := bytes.NewReader(b.Bytes())
	var header [5]uint32
	if err := binary.Read(r, binary.LittleEndian, &header); err != nil {
		t.Fatal(err)
	}
	if header != [5]uint32{9, 3, 3, 0, 0} {
		t.Fatalf("viewer header: %v", header)
	}
	var vertices [9]float32
	var faces [3]uint32
	var colors [3]uint16
	_ = binary.Read(r, binary.LittleEndian, &vertices)
	_ = binary.Read(r, binary.LittleEndian, &faces)
	_ = binary.Read(r, binary.LittleEndian, &colors)
	if vertices[3] != 1 || faces != [3]uint32{0, 1, 2} || colors != [3]uint16{255, 128, 0} {
		t.Fatal("mesh arrays changed")
	}
	var extensions [6]uint32 // textures, stickers, MaterialX, alpha, render class, sim colours
	if err := binary.Read(r, binary.LittleEndian, &extensions); err != nil || extensions != [6]uint32{} || r.Len() != 0 {
		t.Fatalf("extension contract: %v / %v / %d", extensions, err, r.Len())
	}
}

type brokenWriter struct{}

func (brokenWriter) Write([]byte) (int, error) { return 0, errors.New("disk full") }

func TestWriteErrorReachesCLI(t *testing.T) {
	if err := Write(brokenWriter{}, &pipeline.MeshData{}); err == nil {
		t.Fatal("write error discarded")
	}
}

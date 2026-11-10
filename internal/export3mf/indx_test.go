package export3mf

import "testing"

func TestIndxHFGeometryContract(t *testing.T) {
	p := FindPrinter("prusa_coreone_indx_8t")
	if p == nil {
		t.Fatal("INDX printer not registered")
	}
	n := p.FindNozzle("0.4")
	if n == nil || len(n.Processes) != 4 {
		t.Fatal("expected four native 0.4 HF processes")
	}
	m, err := n.loadMachineProfile(p.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(m["nozzle_diameter"].([]any)) != 8 {
		t.Fatal("expected eight physical nozzles")
	}
	for _, pp := range n.Processes {
		if pp.LineWidth != 0.45 || pp.InitialLayerLineWidth != 0.50 || pp.InitialLayerPrintHeight != 0.20 {
			t.Fatalf("%s: grid disagrees with the resolved alpha13 INDX profile: %+v", pp.Name, pp)
		}
	}
}

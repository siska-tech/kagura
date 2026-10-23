# hdl-util/hdmi evaluation source

Upstream: https://github.com/hdl-util/hdmi

Revision: `83b1c9543a91b776671a44e68e130f81cae437b7`.

The ten `src/*.sv` files and both license files are unchanged upstream bytes.
`manifest.json` records the SHA256 of each file. The project uses the
Apache-2.0 option of upstream's MIT OR Apache-2.0 license. Copyright 2019
Sameer Puri; see LICENSE-APACHE and the authorship comments in the source.
No separate upstream NOTICE file was present in the inspected revision.

This directory is a reference/evaluation dependency, not a working Gowin
port. In particular, the upstream serializer and audio CDC must not be
assumed ready for the KAGURA board. Local adapters belong under `rtl/`;
changes to upstream files must update the manifest and record a patch.

Run `tools/check-dependencies.ps1` to detect modified/missing files.

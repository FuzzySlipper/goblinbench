use std::{env, fs, path::PathBuf, process};

fn main() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let output = root.join("ts/packages/contracts/src/generated/door.ts");
    let expected = protocol_door::generated_typescript();
    let check = env::args().skip(1).any(|argument| argument == "--check");

    if check {
        let actual = fs::read_to_string(&output).unwrap_or_default();
        if actual != expected {
            eprintln!("generated door contract is stale; run cargo run -p protocol-codegen");
            process::exit(1);
        }
        println!("generated door contract is current");
        return;
    }

    fs::create_dir_all(output.parent().expect("generated output parent"))
        .expect("create generated output directory");
    fs::write(&output, expected).expect("write generated TypeScript contract");
    println!("wrote {}", output.display());
}

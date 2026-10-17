// music-wrapped-render: renders HTML pages to PNG images with the system WebKit.
// Used for story cards. Pages are laid out at <width> x <height> CSS pixels and saved at exactly
// that many pixels, whatever the screen's scale.
//
// Usage: music-wrapped-render <width> <height> <page.html> <out.png> [<page.html> <out.png> ...]
//        music-wrapped-render --qr <text>   prints a QR code as rows of 0/1 (1 = dark), for `serve`

import AppKit
import CoreImage
import WebKit

let args = CommandLine.arguments

if args.count == 3 && args[1] == "--qr" {
    let filter = CIFilter(name: "CIQRCodeGenerator")!
    filter.setValue(args[2].data(using: .utf8)!, forKey: "inputMessage")
    filter.setValue("M", forKey: "inputCorrectionLevel")
    guard let image = filter.outputImage,
          let cg = CIContext().createCGImage(image, from: image.extent) else { exit(1) }
    // One pixel per module: draw into an 8-bit grey bitmap and read it back.
    let w = cg.width, h = cg.height
    var pixels = [UInt8](repeating: 255, count: w * h)
    let ctx = CGContext(data: &pixels, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
                        space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
    for y in 0..<h {
        print(String((0..<w).map { pixels[y * w + $0] < 128 ? "1" : "0" }))
    }
    exit(0)
}
let width = args.count > 1 ? Double(args[1]) ?? 0 : 0
let height = args.count > 2 ? Double(args[2]) ?? 0 : 0
if args.count < 5 || (args.count - 3) % 2 != 0 || width <= 0 || height <= 0 {
    FileHandle.standardError.write("usage: music-wrapped-render <width> <height> <page.html> <out.png> [...]\n".data(using: .utf8)!)
    exit(2)
}
var jobs = stride(from: 3, to: args.count, by: 2).map { (URL(fileURLWithPath: args[$0]), URL(fileURLWithPath: args[$0 + 1])) }

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)  // no Dock icon, no menu bar

final class Renderer: NSObject, WKNavigationDelegate {
    let view: WKWebView
    var current: (URL, URL)?
    var failures = 0

    override init() {
        view = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        super.init()
        view.navigationDelegate = self
        view.setValue(false, forKey: "drawsBackground")   // transparent pages stay transparent (the app icon)
        // A window that's never shown, so WebKit lays out and paints at the right size.
        let window = NSWindow(contentRect: view.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = view
    }

    func next() {
        guard !jobs.isEmpty else { exit(failures > 0 ? 1 : 0) }
        current = jobs.removeFirst()
        view.loadFileURL(current!.0, allowingReadAccessTo: current!.0.deletingLastPathComponent())
        let started = current!.0
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in   // never hang on one page
            guard let self = self, self.current?.0 == started else { return }
            self.fail("timed out")
        }
    }

    func fail(_ why: String) {
        FileHandle.standardError.write("render failed for \(current?.0.lastPathComponent ?? "?"): \(why)\n".data(using: .utf8)!)
        failures += 1
        current = nil
        next()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { fail("\(error)") }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { fail("\(error)") }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Give fonts, images and the background canvas a moment to paint.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            let config = WKSnapshotConfiguration()
            config.rect = webView.bounds
            webView.takeSnapshot(with: config) { image, error in
                guard let image = image, let job = self.current else { return self.fail("\(String(describing: error))") }
                // Redraw into a bitmap of exactly width x height pixels.
                let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(width), pixelsHigh: Int(height),
                                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
                rep.size = NSSize(width: width, height: height)
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
                image.draw(in: NSRect(x: 0, y: 0, width: width, height: height))
                NSGraphicsContext.restoreGraphicsState()
                do {
                    try rep.representation(using: .png, properties: [:])!.write(to: job.1)
                } catch {
                    return self.fail("\(error)")
                }
                self.current = nil
                self.next()
            }
        }
    }
}

let renderer = Renderer()
renderer.next()
app.run()

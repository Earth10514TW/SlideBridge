import Foundation

public struct MediaItem: Codable, Identifiable, Hashable {
    public var id: String { path }
    public let path: String
    public let format: String
    public let bytes: Int
    public let ole_preview: Bool

    public var fileName: String {
        URL(fileURLWithPath: path).lastPathComponent
    }

    public var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }
}

public struct ScanReport: Codable {
    public let source: String
    public let media: [MediaItem]
    public let ole_objects: Int

    public var emfCount: Int {
        media.filter { $0.format.lowercased() == "emf" }.count
    }

    public var wmfCount: Int {
        media.filter { $0.format.lowercased() == "wmf" }.count
    }
}

public struct ConvertedItem: Codable, Identifiable {
    public var id: String { path }
    public let source: String
    public let path: String
    public let bytes: Int
    public let method: String
}

public struct FixReport: Codable {
    public let source: String
    public let output: String
    public let converted: [ConvertedItem]
    public let updated_relationships: [String]?
    public let retained: Int?
}

public struct DoctorCheck: Codable, Identifiable {
    public var id: String { name }
    public let name: String
    public let status: String // "ok", "warn", "fail", "info"
    public let detail: String
    public let fix: String?
}

public struct DoctorReport: Codable {
    public let checks: [DoctorCheck]
    public let failures: Int
    public let warnings: Int
    public let ready: Bool
}

public struct EditActiveReport: Codable {
    public let status: String
    public let presentation: String
    public let slide_index: Int
    public let shape_name: String
    public let member: String
    public let backup: String?
    public let preview_format: String?
    public let message: String?
    public let is_near_identical: Bool?
}

public enum AppTab: String, CaseIterable, Identifiable {
    case batchRepair = "batchRepair"
    case originEdit = "originEdit"
    case doctor = "doctor"

    public var id: String { rawValue }

    @MainActor
    public func title(using lm: LanguageManager) -> String {
        switch self {
        case .batchRepair: return lm.t(.tabBatchRepair)
        case .originEdit: return lm.t(.tabOriginEdit)
        case .doctor: return lm.t(.tabDoctor)
        }
    }

    public var iconName: String {
        switch self {
        case .batchRepair: return "wand.and.stars"
        case .originEdit: return "chart.xyaxis.line"
        case .doctor: return "stethoscope"
        }
    }
}

public enum UsageMode: String, Codable, CaseIterable, Identifiable {
    case batchOnly = "batchOnly"
    case fullBridge = "fullBridge"

    public var id: String { rawValue }
}

# versioncompatibilityprocess指南

当分析年代久远的 commits 时，可能会遇到以下compatibility问题：

## 常见问题

### 1. Java version不兼容

**症状：**
```
[ERROR] Source option 5 is no longer supported. Use 7 or later.
[ERROR] Target option 5 is no longer supported. Use 7 or later.
[ERROR] invalid target release: 1.5
```

**原因：** 
- 现代 JDK (11+) 不再支持compile Java 5/6 source code
- project pom.xml 中指定了过低的 source/target version

**解决方案：**

1. **使用旧版 JDK（推荐）**
   
   in `config.py` 中设置 `JAVA_HOME`：
   ```python
   class AnalysisConfig:
       JAVA_HOME = "/usr/lib/jvm/java-8-openjdk-amd64"
   ```

2. **使用 SDKMAN 管理多version Java**
   ```bash
   # 安装 SDKMAN
   curl -s "https://get.sdkman.io" | bash
   
   # 安装旧版 Java
   sdk install java 8.0.382-zulu
   
   # inconfiguration中使用
   JAVA_HOME = "/home/user/.sdkman/candidates/java/8.0.382-zulu"
   ```

3. **使用 Maven parameter强制覆盖**
   ```python
   MAVEN_EXTRA_ARGS = "-Dmaven.compiler.source=8 -Dmaven.compiler.target=8"
   ```

### 2. Maven 插件version问题

**症状：**
```
[ERROR] Could not find artifact org.apache.maven.plugins:maven-compiler-plugin:jar:2.3.2
[ERROR] Plugin org.apache.maven.plugins:maven-xxx-plugin:1.0 not found
```

**解决方案：**

1. **使用旧版 Maven**
   ```python
   # 下载旧版 Maven
   # wget https://archive.apache.org/dist/maven/maven-3/3.6.3/binaries/apache-maven-3.6.3-bin.tar.gz
   
   MAVEN_EXECUTABLE = "/opt/apache-maven-3.6.3/bin/mvn"
   ```

2. **使用 Maven Wrapper（如果project提供）**
   - 许多现代project包含 `mvnw` script，会自动使用正确version

### 3. 依赖getfail

**症状：**
```
[ERROR] Could not resolve dependencies for project
[ERROR] Could not find artifact com.example:library:jar:1.0.0
[ERROR] Connection refused
```

**原因：**
- 依赖库已从公共仓库移除
- 仓库 URL 已变更或关闭
- SSL 证书问题

**解决方案：**

1. **configuration镜像仓库**
   
   create或修改 `~/.m2/settings.xml`：
   ```xml
   <settings>
     <mirrors>
       <mirror>
         <id>aliyun</id>
         <mirrorOf>central</mirrorOf>
         <url>https://maven.aliyun.com/repository/central</url>
       </mirror>
     </mirrors>
   </settings>
   ```

2. **添加额外仓库**
   
   某些旧版依赖可能需要从特定仓库get。

3. **process SSL 问题**
   ```python
   MAVEN_EXTRA_ARGS = "-Dmaven.wagon.http.ssl.insecure=true"
   ```

## configuration选项description

in `config.py` 的 `AnalysisConfig` class中：

```python
# ========== versioncompatibilityconfiguration ==========

# Javaversion（设置JAVA_HOMEenvironment变量path，None表示使用系统default）
JAVA_HOME = None

# Maven可executefile path（None表示使用PATH中的mvn）
MAVEN_EXECUTABLE = None

# extra Maven arguments (used to resolve compatibility issues)
MAVEN_EXTRA_ARGS = ""

# whether to skip commits with compatibility issues (instead of marking failed)
SKIP_INCOMPATIBLE_COMMITS = False

# whether to attempt auto-fixing common compatibility issues
AUTO_FIX_COMPATIBILITY = False
```

## 诊断output

当遇到compatibility问题时，工具会inerrorinformation中添加诊断提示：

```
[COMPATIBILITY ISSUES DETECTED]
⚠️  Javaversion不兼容: source-only version过低，当前JDK不支持
⚠️  依赖parseFailed: 无法parseproject依赖

[ERROR] ...具体errorinformation...
```

## 推荐的多versionenvironmentconfiguration

### 方案一：Docker 容器（最isolated）

```dockerfile
FROM maven:3.6.3-jdk-8

WORKDIR /app
COPY . .

# run分析
RUN python analysis.py
```

### 方案二：使用 SDKMAN（推荐）

```bash
# 安装多version Java
sdk install java 8.0.382-zulu
sdk install java 11.0.20-zulu
sdk install java 17.0.8-zulu

# 切换version
sdk use java 8.0.382-zulu

# 然后run分析
python analysis.py
```

### 方案三：project级configuration

createproject特定的configuration：

```python
# 针对特定project的configuration
PROJECT_CONFIGS = {
    'old-project-2010': {
        'JAVA_HOME': '/opt/jdk1.6.0_45',
        'MAVEN_EXECUTABLE': '/opt/apache-maven-2.2.1/bin/mvn'
    },
    'modern-project': {
        'JAVA_HOME': None,  # 使用系统default
        'MAVEN_EXECUTABLE': None
    }
}
```

## 最佳实践

1. **先尝试defaultconfiguration** - 许多project使用 Maven Wrapper 或有兼容的configuration

2. **checkproject文档** - README 通常会description所需的 Java version

3. **查看 pom.xml** - check `maven.compiler.source` 和 `maven.compiler.target`

4. **考虑skip过旧 commits** - 如果只关注较新的test evolution，可以调整 `DATE_FILTER`

5. **使用日期过滤** - in `config.py` 中设置合理的起始日期：
   ```python
   DATE_FILTER = "2016-01-01"  # 只分析 2016 年之后的 commits
   ```

## 常见project的推荐configuration

| project | 推荐 Java | description |
|------|----------|------|
| commons-* 2015前 | Java 6/7 | Apache Commons 旧version |
| commons-* 2015后 | Java 8+ | 现代 Apache Commons |
| Spring 4.x | Java 7/8 | Spring Framework 4 |
| Spring 5.x | Java 8+ | Spring Framework 5 |
| Mockito 2.x | Java 8+ | Mockito 2 系列 |

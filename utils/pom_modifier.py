"""
POM File Modifier - used to dynamically add the JaCoCo plugin
"""

import xml.etree.ElementTree as ET
import os
import shutil
from config import Config
from .logger import get_logger

logger = get_logger()

class PomModifier:
    """POM file modifier"""

    # Maven namespace
    MAVEN_NS = "http://maven.apache.org/POM/4.0.0"

    def __init__(self, pom_path):
        """
        Initialize the POM modifier

        Args:
            pom_path: Path to the pom.xml file
        """
        self.pom_path = pom_path
        self.backup_path = pom_path + ".backup"

    def backup(self):
        """Back up the original pom.xml"""
        if os.path.exists(self.pom_path):
            shutil.copy2(self.pom_path, self.backup_path)
            logger.debug(f"Backed up POM file: {self.backup_path}")
            return True
        return False

    def restore(self):
        """Restore the original pom.xml"""
        if os.path.exists(self.backup_path):
            shutil.copy2(self.backup_path, self.pom_path)
            os.remove(self.backup_path)
            logger.debug(f"Restored POM file: {self.pom_path}")
            return True
        return False

    def add_jacoco_plugin(self):
        """
        Add the JaCoCo plugin to pom.xml

        Returns:
            bool: Whether the addition was successful
        """
        try:
            # Register namespace
            ET.register_namespace('', self.MAVEN_NS)

            # Parse the POM file
            tree = ET.parse(self.pom_path)
            root = tree.getroot()

            # Check if JaCoCo plugin already exists
            if self._has_jacoco_plugin(root):
                logger.debug("JaCoCo plugin already exists in POM file")
                return True

            # Find or create the <build> node
            build = root.find(f"{{{self.MAVEN_NS}}}build")
            if build is None:
                build = ET.SubElement(root, f"{{{self.MAVEN_NS}}}build")

            # Find or create the <plugins> node
            plugins = build.find(f"{{{self.MAVEN_NS}}}plugins")
            if plugins is None:
                plugins = ET.SubElement(build, f"{{{self.MAVEN_NS}}}plugins")

            # Create the JaCoCo plugin configuration
            jacoco_plugin = self._create_jacoco_plugin_xml()
            plugins.append(jacoco_plugin)

            # Save the modified POM
            tree.write(self.pom_path, encoding='utf-8', xml_declaration=True)
            logger.info(f"Added JaCoCo plugin to: {self.pom_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to add JaCoCo plugin: {e}")
            return False

    def _has_jacoco_plugin(self, root):
        """Check whether the JaCoCo plugin already exists"""
        plugins = root.findall(f".//{{{self.MAVEN_NS}}}plugin")
        for plugin in plugins:
            artifact_id = plugin.find(f"{{{self.MAVEN_NS}}}artifactId")
            if artifact_id is not None and artifact_id.text == "jacoco-maven-plugin":
                return True
        return False

    def _create_jacoco_plugin_xml(self):
        """Create the XML configuration for the JaCoCo plugin"""
        # Create plugin element
        plugin = ET.Element(f"{{{self.MAVEN_NS}}}plugin")

        # groupId
        group_id = ET.SubElement(plugin, f"{{{self.MAVEN_NS}}}groupId")
        group_id.text = "org.jacoco"

        # artifactId
        artifact_id = ET.SubElement(plugin, f"{{{self.MAVEN_NS}}}artifactId")
        artifact_id.text = "jacoco-maven-plugin"

        # version
        version = ET.SubElement(plugin, f"{{{self.MAVEN_NS}}}version")
        version.text = Config.JACOCO_VERSION

        # executions
        executions = ET.SubElement(plugin, f"{{{self.MAVEN_NS}}}executions")

        # execution: prepare-agent
        execution1 = ET.SubElement(executions, f"{{{self.MAVEN_NS}}}execution")
        goals1 = ET.SubElement(execution1, f"{{{self.MAVEN_NS}}}goals")
        goal1 = ET.SubElement(goals1, f"{{{self.MAVEN_NS}}}goal")
        goal1.text = "prepare-agent"

        # execution: report
        execution2 = ET.SubElement(executions, f"{{{self.MAVEN_NS}}}execution")
        id2 = ET.SubElement(execution2, f"{{{self.MAVEN_NS}}}id")
        id2.text = "report"
        phase2 = ET.SubElement(execution2, f"{{{self.MAVEN_NS}}}phase")
        phase2.text = "test"
        goals2 = ET.SubElement(execution2, f"{{{self.MAVEN_NS}}}goals")
        goal2 = ET.SubElement(goals2, f"{{{self.MAVEN_NS}}}goal")
        goal2.text = "report"

        return plugin

    def __enter__(self):
        """Context manager entry"""
        self.backup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.restore()
        return False
